"""业务操作 API — 信息更新"""
import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.model.schemas import ApiResponse

router = APIRouter()

ALLOWED_FIELDS = {"phone", "email", "occupation", "education"}


@router.put("/contact")
async def update_contact(body: dict, db: AsyncSession = Depends(get_db)) -> ApiResponse:
    """更新客户联系信息"""
    customer_id = body.get("customer_id")
    field = body.get("field", "")
    value = body.get("value", "")

    if not customer_id or field not in ALLOWED_FIELDS or not value:
        return ApiResponse(code=400, message=f"参数不完整，允许字段: {ALLOWED_FIELDS}", trace_id=uuid.uuid4().hex[:8])

    await db.execute(text(f"UPDATE sys_user SET {field}=:v, update_time=NOW() WHERE id=:c"), {"v": value, "c": customer_id})
    await db.commit()
    return ApiResponse(code=200, message="更新成功", data={"customer_id": customer_id, "field": field}, trace_id=uuid.uuid4().hex[:8])
