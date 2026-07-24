"""业务操作 API — 产品赎回"""
import uuid
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.model.schemas import ApiResponse
from app.service.transaction_flow_service import TransactionFlowService
from app.security.authorization import authenticated_actor_id, require_roles
from app.tool.neo4j_sync import remove_holding, sync_holding

router = APIRouter()
_transaction_flow = TransactionFlowService()
_logger = logging.getLogger(__name__)


@router.post("/redeem")
async def redeem_product(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("理财顾问", "管理员")),
) -> ApiResponse:
    """产品赎回：校验持仓 → 计算金额 → 写入流水 → 更新持仓"""
    customer_id = body.get("customer_id")
    product_id = body.get("product_id")
    shares = Decimal(str(body.get("shares", 0)))
    operator_id = authenticated_actor_id(user, body.get("operator_id"))
    idempotency_key = body.get("idempotency_key")  # 修复 1.2：支持幂等性检查

    if not customer_id or not product_id or shares <= 0:
        return ApiResponse(code=400, message="参数不完整", trace_id=uuid.uuid4().hex[:8])

    # 修复 1.2：检查幂等性
    if idempotency_key:
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

    # 查持仓（加行锁防止并发）
    holding = await db.execute(
        text("SELECT * FROM fin_holdings WHERE customer_id=:cid AND product_id=:pid AND status='持有中' FOR UPDATE"),
        {"cid": customer_id, "pid": product_id},
    )
    holding = holding.mappings().first()
    if not holding:
        return ApiResponse(code=404, message="无该产品的持仓", trace_id=uuid.uuid4().hex[:8])

    holding_shares = Decimal(str(holding["shares"] or 0))
    if shares > holding_shares:
        return ApiResponse(code=400, message=f"赎回份额 {shares} 超过持有份额 {holding_shares}", trace_id=uuid.uuid4().hex[:8])

    # 查询产品以获取 expected_return（修复 1.1：使用 expected_return 计算 Mock 净值）
    product_row = await db.execute(
        text("SELECT expected_return FROM fin_product WHERE id = :pid"),
        {"pid": product_id},
    )
    product = product_row.mappings().first()
    if not product:
        return ApiResponse(code=404, message="产品不存在", trace_id=uuid.uuid4().hex[:8])

    # Mock 净值计算：假设初始净值为 1，按年化收益率折算到每日
    annual_return = Decimal(str(product["expected_return"] or 0)) / Decimal("100")
    daily_return = annual_return / Decimal("365")
    nav = Decimal("1") + daily_return
    amount = shares * nav

    # 写流水（修复 1.2：存储幂等键）
    txn_no = f"TXN{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
    if idempotency_key:
        txn_no = f"{txn_no}[idempotency:{idempotency_key}]"

    await db.execute(
        text("INSERT INTO fin_transaction (transaction_no,customer_id,product_id,transaction_type,amount,shares,nav,fee,status,operator_id,remark) VALUES (:t,:c,:p,'redeem',:a,:s,:n,0,'已确认',:o,:r)"),
        {"t": txn_no, "c": customer_id, "p": product_id, "a": float(amount), "s": float(shares), "n": float(nav), "o": operator_id, "r": "赎回"},
    )

    # 更新持仓（全程 Decimal 计算，使用 quantize 保持精度）
    remaining = holding_shares - shares
    original_cost = Decimal(str(holding["cost_amount"] or 0))
    if remaining <= 0:
        await db.execute(text("UPDATE fin_holdings SET status='已赎回', update_time=NOW() WHERE id=:id"), {"id": holding["id"]})
    else:
        # 按比例减少 cost_amount，保持盈亏计算准确（修复 2.2 + 精度损失修复）
        # 使用 quantize 保持精度，避免多次赎回后的累积误差
        redemption_ratio = (shares / holding_shares).quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_UP
        )
        new_cost = (original_cost * (Decimal("1") - redemption_ratio)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
        await db.execute(text("UPDATE fin_holdings SET shares=:s, cost_amount=:cost, current_value=:v, update_time=NOW() WHERE id=:id"),
                         {"s": float(remaining), "cost": float(new_cost), "v": float(remaining * nav), "id": holding["id"]})

    risk_monitor = await _transaction_flow.monitor(
        db,
        {
            "customer_id": customer_id,
            "transaction_id": txn_no,
            "amount": float(amount),
            "transaction_type": "redeem",
            "timestamp": datetime.now().isoformat(),
        },
    )
    await db.commit()
    try:
        if remaining <= 0:
            await remove_holding(customer_id, product_id)
        else:
            await sync_holding(customer_id, product_id, float(remaining), float(remaining * nav))
    except Exception as exc:
        _logger.warning("Neo4j holding sync failed after redeem customer=%s product=%s: %s", customer_id, product_id, exc)
    return ApiResponse(
        code=200,
        message="赎回成功",
        data={
            "transaction_no": txn_no,
            "shares": float(shares),
            "amount": float(amount),
            "risk_monitor": risk_monitor,
        },
        trace_id=uuid.uuid4().hex[:8],
    )
