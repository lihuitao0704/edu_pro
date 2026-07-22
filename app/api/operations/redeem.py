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
    shares = float(body.get("shares", 0))
    operator_id = body.get("operator_id")

    if not customer_id or not product_id or shares <= 0:
        return ApiResponse(code=400, message="参数不完整", trace_id=uuid.uuid4().hex[:8])

    # 查持仓
    holding = await db.execute(
        text("SELECT * FROM fin_holdings WHERE customer_id=:cid AND product_id=:pid AND status='持有中'"),
        {"cid": customer_id, "pid": product_id},
    )
    holding = holding.mappings().first()
    if not holding:
        return ApiResponse(code=404, message="无该产品的持仓", trace_id=uuid.uuid4().hex[:8])

    if shares > float(holding["shares"] or 0):
        return ApiResponse(code=400, message=f"赎回份额 {shares} 超过持有份额 {holding['shares']}", trace_id=uuid.uuid4().hex[:8])

    nav = Decimal("1.000000")
    amount = Decimal(str(shares)) * nav

    # 写流水
    txn_no = f"TXN{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
    await db.execute(
        text("INSERT INTO fin_transaction (transaction_no,customer_id,product_id,transaction_type,amount,shares,nav,fee,status,operator_id,remark) VALUES (:t,:c,:p,'redeem',:a,:s,:n,0,'已确认',:o,:r)"),
        {"t": txn_no, "c": customer_id, "p": product_id, "a": float(amount), "s": shares, "n": float(nav), "o": operator_id, "r": "赎回"},
    )

    # 更新持仓
    remaining = float(holding["shares"]) - shares
    if remaining <= 0.001:
        await db.execute(text("UPDATE fin_holdings SET status='已赎回', update_time=NOW() WHERE id=:id"), {"id": holding["id"]})
    else:
        await db.execute(text("UPDATE fin_holdings SET shares=:s, current_value=:v, update_time=NOW() WHERE id=:id"),
                         {"s": remaining, "v": remaining * float(nav), "id": holding["id"]})

    await db.commit()
    return ApiResponse(code=200, message="赎回成功", data={"transaction_no": txn_no, "shares": shares, "amount": float(amount)}, trace_id=uuid.uuid4().hex[:8])
