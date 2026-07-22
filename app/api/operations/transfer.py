"""业务操作 API — 转账"""
import asyncio
import uuid
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.model.schemas import ApiResponse

router = APIRouter()

# 确保 sys_user 表有 balance 列（幂等执行，不影响已有数据）
_balance_column_ready = False
_balance_lock = asyncio.Lock()


async def _ensure_balance_column(db: AsyncSession):
    global _balance_column_ready
    if _balance_column_ready:
        return
    async with _balance_lock:
        if _balance_column_ready:  # double-check after acquiring lock
            return
        try:
            await db.execute(text(
                "ALTER TABLE sys_user ADD COLUMN balance DECIMAL(18,2) NOT NULL DEFAULT 0.00"
            ))
            await db.commit()
        except Exception:
            # 列已存在则忽略
            pass
        _balance_column_ready = True


@router.post("/transfer")
async def transfer_funds(body: dict, db: AsyncSession = Depends(get_db)) -> ApiResponse:
    """转账：校验余额 → 扣款 → 入账 → 双方流水"""
    await _ensure_balance_column(db)

    from_id = body.get("from_customer_id")
    to_id = body.get("to_customer_id")
    amount = Decimal(str(body.get("amount", 0)))
    operator_id = body.get("operator_id")

    if not from_id or not to_id or amount <= 0:
        return ApiResponse(code=400, message="参数不完整", trace_id=uuid.uuid4().hex[:8])
    if from_id == to_id:
        return ApiResponse(code=400, message="不能转给自己", trace_id=uuid.uuid4().hex[:8])

    # 锁定发送方账户，检查余额
    sender_row = await db.execute(
        text("SELECT balance FROM sys_user WHERE id = :id FOR UPDATE"),
        {"id": from_id},
    )
    sender = sender_row.mappings().first()
    if not sender:
        return ApiResponse(code=404, message="转出账户不存在", trace_id=uuid.uuid4().hex[:8])

    sender_balance = Decimal(str(sender["balance"] or 0))
    if sender_balance < amount:
        return ApiResponse(
            code=400,
            message=f"余额不足：当前余额 {sender_balance} 元，转账金额 {amount} 元",
            trace_id=uuid.uuid4().hex[:8],
        )

    # 确认接收方存在
    receiver_row = await db.execute(
        text("SELECT id FROM sys_user WHERE id = :id"),
        {"id": to_id},
    )
    if not receiver_row.first():
        return ApiResponse(code=404, message="接收账户不存在", trace_id=uuid.uuid4().hex[:8])

    # 扣减发送方余额
    await db.execute(
        text("UPDATE sys_user SET balance = balance - :amt, update_time = NOW() WHERE id = :id"),
        {"amt": amount, "id": from_id},
    )
    # 增加接收方余额
    await db.execute(
        text("UPDATE sys_user SET balance = balance + :amt, update_time = NOW() WHERE id = :id"),
        {"amt": amount, "id": to_id},
    )

    # 记录双方流水（product_id=0: 转账非产品交易，用 0 占位，因为该列 NOT NULL）
    txn_no = f"TXN{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
    await db.execute(
        text("INSERT INTO fin_transaction (transaction_no,customer_id,product_id,transaction_type,amount,status,operator_id,remark) "
             "VALUES (:t,:c,0,'transfer_out',:a,'已确认',:o,:r)"),
        {"t": txn_no, "c": from_id, "a": amount, "o": operator_id, "r": f"转账至客户{to_id}"},
    )
    txn_no_in = f"TXN{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
    await db.execute(
        text("INSERT INTO fin_transaction (transaction_no,customer_id,product_id,transaction_type,amount,status,operator_id,remark) "
             "VALUES (:t,:c,0,'transfer_in',:a,'已确认',:o,:r)"),
        {"t": txn_no_in, "c": to_id, "a": amount, "o": operator_id, "r": f"收到客户{from_id}转账"},
    )

    await db.commit()
    return ApiResponse(
        code=200,
        message="转账成功",
        data={"transaction_no": txn_no, "amount": float(amount), "to_customer_id": to_id},
        trace_id=uuid.uuid4().hex[:8],
    )
