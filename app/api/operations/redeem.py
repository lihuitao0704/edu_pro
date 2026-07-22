"""业务操作 API — 产品赎回"""
import uuid
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.model.schemas import ApiResponse

router = APIRouter()


@router.post("/redeem")
async def redeem_product(body: dict, db: AsyncSession = Depends(get_db)) -> ApiResponse:
    """产品赎回：校验持仓 → 计算金额 → 写入流水 → 更新持仓"""
    customer_id = body.get("customer_id")
    product_id = body.get("product_id")
    shares = Decimal(str(body.get("shares", 0)))
    operator_id = body.get("operator_id")

    if not customer_id or not product_id or shares <= 0:
        return ApiResponse(code=400, message="参数不完整", trace_id=uuid.uuid4().hex[:8])

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

    nav = Decimal("1.000000")
    amount = shares * nav

    # 写流水
    txn_no = f"TXN{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
    await db.execute(
        text("INSERT INTO fin_transaction (transaction_no,customer_id,product_id,transaction_type,amount,shares,nav,fee,status,operator_id,remark) VALUES (:t,:c,:p,'redeem',:a,:s,:n,0,'已确认',:o,:r)"),
        {"t": txn_no, "c": customer_id, "p": product_id, "a": float(amount), "s": float(shares), "n": float(nav), "o": operator_id, "r": "赎回"},
    )

    # 更新持仓（全程 Decimal 计算）
    remaining = holding_shares - shares
    original_cost = Decimal(str(holding["cost_amount"] or 0))
    if remaining <= 0:
        await db.execute(text("UPDATE fin_holdings SET status='已赎回', update_time=NOW() WHERE id=:id"), {"id": holding["id"]})
    else:
        # 按比例减少 cost_amount，保持盈亏计算准确
        redemption_ratio = shares / holding_shares
        new_cost = original_cost * (1 - redemption_ratio)
        await db.execute(text("UPDATE fin_holdings SET shares=:s, cost_amount=:cost, current_value=:v, update_time=NOW() WHERE id=:id"),
                         {"s": float(remaining), "cost": float(new_cost), "v": float(remaining * nav), "id": holding["id"]})

    await db.commit()
    return ApiResponse(code=200, message="赎回成功", data={"transaction_no": txn_no, "shares": float(shares), "amount": float(amount)}, trace_id=uuid.uuid4().hex[:8])
