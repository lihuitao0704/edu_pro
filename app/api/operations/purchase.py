"""
业务操作 API — 产品申购
负责人: LHG
"""

import json
import uuid
import asyncio
import logging
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy.exc as sa_exc

from app.config.database import get_db
from app.model.schemas import ApiResponse
from app.service.transaction_flow_service import TransactionFlowService
from app.security.authorization import authenticated_actor_id, require_roles
from app.tool.neo4j_sync import sync_holding

router = APIRouter()
_transaction_flow = TransactionFlowService()
_logger = logging.getLogger(__name__)


def generate_transaction_no() -> str:
    """生成交易流水号: TXN + 时间戳 + 随机"""
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    rand = uuid.uuid4().hex[:6].upper()
    return f"TXN{ts}{rand}"


def calc_nav_time() -> str:
    """判断适用净值：15:00前按T日，之后T+1"""
    now = datetime.now()
    if now.hour < 15:
        return now.strftime("%Y-%m-%d")
    else:
        from datetime import timedelta
        return (now + timedelta(days=1)).strftime("%Y-%m-%d")


@router.post("/purchase")
async def purchase_product(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("理财顾问", "管理员")),
) -> ApiResponse:
    """
    产品申购
    body: {customer_id, product_id, amount, operator_id}
    流程:
      1. 校验产品是否存在且在售
      2. 校验适当性（客户风险等级 >= 产品风险等级）
      3. 校验金额 >= 产品起投金额
      4. 写入交易流水
      5. 更新/新建持仓
      6. 返回结果
    """
    customer_id = body.get("customer_id")
    product_id = body.get("product_id")
    amount = Decimal(str(body.get("amount", 0)))
    operator_id = authenticated_actor_id(user, body.get("operator_id"))
    idempotency_key = body.get("idempotency_key")

    if not customer_id or not product_id or amount <= 0:
        return ApiResponse(code=400, message="参数不完整", trace_id=uuid.uuid4().hex[:8])

    # API 层金额上限校验（防止绕过 operator_agent 直接调用）
    MAX_PURCHASE_AMOUNT = Decimal("10000000")  # 1000 万
    if amount > MAX_PURCHASE_AMOUNT:
        return ApiResponse(
            code=400,
            message=f"申购金额 {amount} 元超过单笔上限 {MAX_PURCHASE_AMOUNT} 元",
            trace_id=uuid.uuid4().hex[:8],
        )

    # 1. 查询产品信息（加行锁防止并发申购下架产品）
    product = await db.execute(
        text("SELECT * FROM fin_product WHERE id = :pid AND status = '在售' FOR UPDATE"),
        {"pid": product_id},
    )
    product = product.mappings().first()
    if not product:
        return ApiResponse(code=404, message="产品不存在或已下架", trace_id=uuid.uuid4().hex[:8])

    # 2. 适当性校验
    profile = await db.execute(
        text("SELECT risk_level FROM fin_risk_assessment WHERE customer_id = :cid "
             "ORDER BY create_time DESC LIMIT 1"),
        {"cid": customer_id},
    )
    profile = profile.mappings().first()
    if not profile:
        return ApiResponse(code=400, message="客户尚未完成风险评估，无法申购",
                           trace_id=uuid.uuid4().hex[:8])

    # 风险等级匹配: 中文 → R1-R5
    customer_level = profile["risk_level"]
    level_map = {"保守型":"R1","稳健型":"R2","平衡型":"R3","进取型":"R4","激进型":"R5","C1":"R1","C2":"R2","C3":"R3","C4":"R4","C5":"R5"}
    customer_level = level_map.get(customer_level, customer_level.replace("C","R"))
    product_level = product["risk_level"]
    level_order = {"R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}
    if level_order.get(customer_level, 0) < level_order.get(product_level, 0):
        return ApiResponse(
            code=400,
            message=f"适当性不匹配：客户风险等级 {profile['risk_level']}，产品风险等级 {product_level}",
            trace_id=uuid.uuid4().hex[:8],
        )

    # 3. 起投金额校验
    min_amount = Decimal(str(product["min_amount"] or 1000))
    if amount < min_amount:
        return ApiResponse(
            code=400,
            message=f"申购金额 {amount} 元低于起投金额 {min_amount} 元",
            trace_id=uuid.uuid4().hex[:8],
        )

    # 4. 获取当前净值
    # 优先级: fin_product_nav 表 > product.current_nav 字段 > 基于 expected_return 估算
    nav = None
    nav_source = "estimated"  # 记录净值来源，便于审计

    # 4a. 尝试从净值表查询最新净值
    try:
        nav_row = await db.execute(
            text("SELECT nav_value FROM fin_product_nav WHERE product_id = :pid ORDER BY nav_date DESC LIMIT 1"),
            {"pid": product_id},
        )
        nav_data = nav_row.mappings().first()
        if nav_data and nav_data.get("nav_value"):
            nav = Decimal(str(nav_data["nav_value"]))
            nav_source = "nav_table"
    except Exception:
        pass  # 表可能不存在

    # 4b. 回退：使用产品表 current_nav 字段
    if nav is None:
        current_nav = product.get("current_nav")
        if current_nav is not None:
            nav = Decimal(str(current_nav))
            nav_source = "product_field"

    # 4c. 最终回退：基于 expected_return 估算（净值 = 1 + 历史累计收益估算）
    if nav is None:
        annual_return = Decimal(str(product.get("expected_return", 0))) / Decimal("100")
        # 估算：假设产品已存续 180 天，按年化收益率线性累加
        nav = Decimal("1") + annual_return * Decimal("180") / Decimal("365")
        nav_source = "estimated"
        _logger.info("净值估算 product=%s nav=%s (来源: expected_return=%s)", product_id, nav, product.get("expected_return"))

    # 5. 计算份额（金额/净值，简化无手续费）— 全程 Decimal
    shares = amount / nav

    # 6. 写入交易流水（含幂等性检查）
    txn_no = generate_transaction_no()
    if idempotency_key:
        # 检查是否已存在相同幂等键的交易
        existing = await db.execute(
            text("SELECT transaction_no FROM fin_transaction WHERE remark LIKE :key LIMIT 1"),
            {"key": f"%[idempotency:{idempotency_key}]%"},
        )
        if existing_txn := existing.scalar():
            return ApiResponse(
                code=200,
                message="重复请求，返回原交易结果",
                data={"transaction_no": existing_txn, "duplicate": True},
                trace_id=uuid.uuid4().hex[:8],
            )
        # 将幂等键存入 remark 字段（实际生产环境应有独立的 idempotency_key 列）
        txn_no = f"{txn_no}[idempotency:{idempotency_key}]"

    await db.execute(
        text("""
            INSERT INTO fin_transaction
            (transaction_no, customer_id, product_id, transaction_type,
             amount, shares, nav, fee, status, operator_id, remark)
            VALUES
            (:txn_no, :cid, :pid, 'purchase', :amount, :shares, :nav, 0, '已确认', :oid, :remark)
        """),
        {
            "txn_no": txn_no,
            "cid": customer_id,
            "pid": product_id,
            "amount": float(amount),
            "shares": float(shares),
            "nav": float(nav),
            "oid": operator_id,
            "remark": f"申购 {product['product_name']}",
        },
    )

    # 7. 更新或新建持仓（加行锁防止并发）+ 死锁检测和重试
    MAX_RETRY = 3
    for attempt in range(MAX_RETRY):
        try:
            existing = await db.execute(
                text("SELECT id, shares, cost_amount FROM fin_holdings "
                     "WHERE customer_id = :cid AND product_id = :pid AND status = '持有中' FOR UPDATE"),
                {"cid": customer_id, "pid": product_id},
            )
            existing = existing.mappings().first()

            if existing:
                # DB 返回 Numeric → 自动映射为 Decimal，直接相加无精度损失
                existing_shares = Decimal(str(existing["shares"] or 0))
                existing_cost = Decimal(str(existing["cost_amount"] or 0))
                new_shares = existing_shares + shares
                new_cost = existing_cost + amount
                await db.execute(
                    text("UPDATE fin_holdings SET shares = :s, cost_amount = :c, "
                         "current_value = :v, update_time = NOW() WHERE id = :id"),
                    {"s": float(new_shares), "c": float(new_cost), "v": float(new_cost), "id": existing["id"]},
                )
                synced_shares = float(new_shares)
                synced_value = float(new_cost)
            else:
                await db.execute(
                    text("""
                        INSERT INTO fin_holdings
                        (customer_id, product_id, shares, cost_amount, current_value, status)
                        VALUES (:cid, :pid, :s, :c, :v, '持有中')
                    """),
                    {"cid": customer_id, "pid": product_id, "s": float(shares),
                     "c": float(amount), "v": float(amount)},
                )
                synced_shares = float(shares)
                synced_value = float(amount)

            risk_monitor = await _transaction_flow.monitor(
                db,
                {
                    "customer_id": customer_id,
                    "transaction_id": txn_no,
                    "amount": float(amount),
                    "transaction_type": "purchase",
                    "timestamp": datetime.now().isoformat(),
                    "investor_account": str(customer_id),
                },
            )

            # ── 事务性写入图谱同步意图（outbox 模式）──
            # 在 commit 前将 Neo4j 同步意图写入 retry 表，确保不会丢失
            await db.execute(
                text("""
                    INSERT INTO fin_graph_sync_retry
                    (sync_type, payload, error_message, retry_count, max_retries, next_retry_at, status)
                    VALUES ('holding', :payload, '', 0, 10, NOW(), 'pending')
                """),
                {
                    "payload": json.dumps({
                        "customer_id": customer_id,
                        "product_id": product_id,
                        "shares": synced_shares,
                        "current_value": synced_value,
                    }, ensure_ascii=False),
                },
            )
            await db.commit()

            # ── 立即尝试 Neo4j 同步（尽力而为，失败由 retry scheduler 补偿）──
            try:
                await sync_holding(customer_id, product_id, synced_shares, synced_value)
                # 同步成功，标记 outbox 记录为 success
                try:
                    await db.execute(
                        text("UPDATE fin_graph_sync_retry SET status = 'success', updated_at = NOW() WHERE sync_type = 'holding' AND JSON_EXTRACT(payload, '$.customer_id') = :cid AND JSON_EXTRACT(payload, '$.product_id') = :pid AND status = 'pending' ORDER BY id DESC LIMIT 1"),
                        {"cid": customer_id, "pid": product_id},
                    )
                    await db.commit()
                except Exception:
                    pass  # outbox 更新失败不影响主流程
            except Exception as exc:
                _logger.warning("Neo4j holding sync failed after purchase customer=%s product=%s: %s", customer_id, product_id, exc)
                try:
                    from app.api.admin import inc_metric
                    inc_metric("neo4j_sync_failures")
                except Exception:
                    pass
                # 更新 outbox 记录的错误信息
                try:
                    await db.execute(
                        text("UPDATE fin_graph_sync_retry SET error_message = :msg, updated_at = NOW() WHERE sync_type = 'holding' AND JSON_EXTRACT(payload, '$.customer_id') = :cid AND JSON_EXTRACT(payload, '$.product_id') = :pid AND status = 'pending' ORDER BY id DESC LIMIT 1"),
                        {"msg": str(exc)[:1024], "cid": customer_id, "pid": product_id},
                    )
                    await db.commit()
                except Exception:
                    pass

            # ── Issue #5 修复：购买行为触发画像重新研判（反馈闭环）──
            try:
                from app.service.profile_service import ProfileService
                profile_svc = ProfileService(db)
                engine_result = await profile_svc.assess(customer_id, trigger_type="purchase")
                _logger.info(
                    "购买后画像更新完成 customer=%s level=%s breakers=%d warnings=%d",
                    customer_id,
                    engine_result.risk_level,
                    len(engine_result.circuit_breakers),
                    len(engine_result.warnings),
                )
            except Exception as exc:
                _logger.warning("购买后画像更新失败 customer=%s (不影响主流程): %s", customer_id, exc)

            break  # 成功，退出重试循环

        except sa_exc.DeadlockDetected as e:
            _logger.warning(f"申购死锁检测，重试 {attempt + 1}/{MAX_RETRY}: {e}")
            await db.rollback()
            await asyncio.sleep(0.1 * (attempt + 1))  # 指数退避
            if attempt == MAX_RETRY - 1:
                return ApiResponse(
                    code=500,
                    message="系统繁忙，请稍后重试",
                    trace_id=uuid.uuid4().hex[:8],
                )
        except Exception as e:
            await db.rollback()
            _logger.error(f"申购持仓更新失败: {e}")
            try:
                from app.api.admin import inc_metric
                inc_metric("purchase_errors")
            except Exception:
                pass
            raise

    try:
        from app.api.admin import inc_metric
        inc_metric("purchase_total")
    except Exception:
        pass

    return ApiResponse(
        code=200,
        message="申购成功",
        data={
            "transaction_no": txn_no,
            "product_name": product["product_name"],
            "amount": float(amount),
            "shares": float(shares),
            "nav": float(nav),
            "nav_source": nav_source,
            "nav_date": calc_nav_time(),
            "risk_monitor": risk_monitor,
        },
        trace_id=uuid.uuid4().hex[:8],
    )
