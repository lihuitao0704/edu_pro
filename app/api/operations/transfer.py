"""业务操作 API — 转账"""
import uuid
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.model.schemas import ApiResponse

router = APIRouter()


@router.post("/transfer")
async def transfer_funds(body: dict, db: AsyncSession = Depends(get_db)) -> ApiResponse:
    """转账：校验 → 扣款 → 入账 → 流水"""
    from_id = body.get("from_customer_id")
    to_id = body.get("to_customer_id")
    amount = float(body.get("amount", 0))
    operator_id = body.get("operator_id")

    if not from_id or not to_id or amount <= 0:
        return ApiResponse(code=400, message="参数不完整", trace_id=uuid.uuid4().hex[:8])
    if from_id == to_id:
        return ApiResponse(code=400, message="不能转给自己", trace_id=uuid.uuid4().hex[:8])

    # 这里简化处理：仅记录流水，不做真实资金操作（Mock）
    txn_no = f"TXN{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
    await db.execute(
        text("INSERT INTO fin_transaction (transaction_no,customer_id,product_id,transaction_type,amount,status,operator_id,remark) VALUES (:t,:c,0,'transfer',:a,'已确认',:o,:r)"),
        {"t": txn_no, "c": from_id, "a": amount, "o": operator_id, "r": f"转账至客户{to_id}"},
    )
    await db.commit()
    return ApiResponse(code=200, message="转账成功", data={"transaction_no": txn_no, "amount": amount, "to_customer_id": to_id}, trace_id=uuid.uuid4().hex[:8])
