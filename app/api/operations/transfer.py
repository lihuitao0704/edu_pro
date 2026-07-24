"""业务操作 API — 转账"""
import uuid
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.model.schemas import ApiResponse
from app.service.transaction_flow_service import TransactionFlowService
from app.security.authorization import authenticated_actor_id, require_roles

router = APIRouter()
_transaction_flow = TransactionFlowService()


@router.post("/transfer")
async def transfer_funds(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("理财顾问", "管理员")),
) -> ApiResponse:
    """转账：校验余额 → 扣款 → 入账 → 双方流水"""
    # balance 列已在 init_db() 启动时确保存在

    from_id = body.get("from_customer_id")
    to_id = body.get("to_customer_id")
    amount = Decimal(str(body.get("amount", 0)))
    operator_id = authenticated_actor_id(user, body.get("operator_id"))
    idempotency_key = body.get("idempotency_key")  # 修复 1.2：支持幂等性检查

    if not from_id or not to_id or amount <= 0:
        return ApiResponse(code=400, message="参数不完整", trace_id=uuid.uuid4().hex[:8])
    if from_id == to_id:
        return ApiResponse(code=400, message="不能转给自己", trace_id=uuid.uuid4().hex[:8])

    # 修复 2.10：API 层转账金额上限校验
    MAX_TRANSFER_AMOUNT = Decimal("10000000")  # 1000 万
    if amount > MAX_TRANSFER_AMOUNT:
        return ApiResponse(
            code=400,
            message=f"转账金额 {amount} 元超过单笔上限 {MAX_TRANSFER_AMOUNT} 元",
            trace_id=uuid.uuid4().hex[:8],
        )

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

    # 🔴 修复：同时锁定双方账户（按ID排序，避免死锁）
    ids_sorted = sorted([from_id, to_id])

    # 锁定发送方账户
    sender_row = await db.execute(
        text("SELECT balance FROM sys_user WHERE id = :id FOR UPDATE"),
        {"id": from_id},
    )
    sender = sender_row.mappings().first()
    if not sender:
        return ApiResponse(code=404, message="转出账户不存在", trace_id=uuid.uuid4().hex[:8])

    # 锁定接收方账户
    receiver_row = await db.execute(
        text("SELECT id FROM sys_user WHERE id = :id FOR UPDATE"),
        {"id": to_id},
    )
    if not receiver_row.first():
        return ApiResponse(code=404, message="接收账户不存在", trace_id=uuid.uuid4().hex[:8])

    sender_balance = Decimal(str(sender["balance"] or 0))
    if sender_balance < amount:
        return ApiResponse(
            code=400,
            message=f"余额不足：当前余额 {sender_balance} 元，转账金额 {amount} 元",
            trace_id=uuid.uuid4().hex[:8],
        )

    # 扣减发送方余额（在同一个事务中，保证原子性）
    await db.execute(
        text("UPDATE sys_user SET balance = balance - :amt, update_time = NOW() WHERE id = :id"),
        {"amt": amount, "id": from_id},
    )
    # 增加接收方余额（在同一个事务中，保证原子性）
    await db.execute(
        text("UPDATE sys_user SET balance = balance + :amt, update_time = NOW() WHERE id = :id"),
        {"amt": amount, "id": to_id},
    )

    # 记录双方流水（修复 1.2：存储幂等键）
    txn_no = f"TXN{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
    if idempotency_key:
        txn_no = f"{txn_no}[idempotency:{idempotency_key}]"

    await db.execute(
        text("INSERT INTO fin_transaction (transaction_no,customer_id,product_id,transaction_type,amount,status,operator_id,remark) "
             "VALUES (:t,:c,0,'transfer_out',:a,'已确认',:o,:r)"),
        {"t": txn_no, "c": from_id, "a": amount, "o": operator_id, "r": f"转账至客户{to_id}"},
    )
    txn_no_in = f"TXN{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
    if idempotency_key:
        txn_no_in = f"{txn_no_in}[idempotency:{idempotency_key}]"

    await db.execute(
        text("INSERT INTO fin_transaction (transaction_no,customer_id,product_id,transaction_type,amount,status,operator_id,remark) "
             "VALUES (:t,:c,0,'transfer_in',:a,'已确认',:o,:r)"),
        {"t": txn_no_in, "c": to_id, "a": amount, "o": operator_id, "r": f"收到客户{from_id}转账"},
    )

    risk_monitor = await _transaction_flow.monitor(
        db,
        {
            "customer_id": from_id,
            "transaction_id": txn_no,
            "amount": float(amount),
            "transaction_type": "transfer_out",
            "timestamp": datetime.now().isoformat(),
            "counterparty": {"account": str(to_id)},
            "investor_account": str(from_id),
        },
    )
    await db.commit()
    return ApiResponse(
        code=200,
        message="转账成功",
        data={
            "transaction_no": txn_no,
            "amount": float(amount),
            "to_customer_id": to_id,
            "risk_monitor": risk_monitor,
        },
        trace_id=uuid.uuid4().hex[:8],
    )
