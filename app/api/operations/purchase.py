"""
业务操作 API — 产品申购
负责人: LHG
"""

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.model.schemas import ApiResponse

router = APIRouter()


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
async def purchase_product(body: dict, db: AsyncSession = Depends(get_db)) -> ApiResponse:
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
    operator_id = body.get("operator_id")

    if not customer_id or not product_id or amount <= 0:
        return ApiResponse(code=400, message="参数不完整", trace_id=uuid.uuid4().hex[:8])

    # 1. 查询产品信息
    product = await db.execute(
        text("SELECT * FROM fin_product WHERE id = :pid AND status = '在售'"),
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

    # 4. 获取当前净值（Mock：用 expected_return 模拟）
    nav = Decimal("1.000000")  # 简化：净值为1

    # 5. 计算份额（金额/净值，简化无手续费）— 全程 Decimal
    shares = amount / nav

    # 6. 写入交易流水
    txn_no = generate_transaction_no()
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

    # 7. 更新或新建持仓（加行锁防止并发）
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

    await db.commit()

    return ApiResponse(
        code=200,
        message="申购成功",
        data={
            "transaction_no": txn_no,
            "product_name": product["product_name"],
            "amount": float(amount),
            "shares": float(shares),
            "nav": float(nav),
            "nav_date": calc_nav_time(),
        },
        trace_id=uuid.uuid4().hex[:8],
    )
