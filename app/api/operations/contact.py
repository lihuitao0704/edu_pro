"""业务操作 API — 信息更新"""
import re
import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.model.schemas import ApiResponse
from app.security.authorization import require_roles

router = APIRouter()

ALLOWED_FIELDS = {"phone", "email", "occupation", "education"}

# 安全的列名映射（白名单 → 合法SQL列名），杜绝注入
_COLUMN_MAP = {
    "phone": "phone",
    "email": "email",
    "occupation": "occupation",
    "education": "education",
}


@router.put("/contact")
async def update_contact(
    body: dict,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_roles("客户经理", "管理员")),
) -> ApiResponse:
    """更新客户联系信息"""
    customer_id = body.get("customer_id")
    field = body.get("field", "")
    value = body.get("value", "")

    if not customer_id or field not in ALLOWED_FIELDS or not value:
        return ApiResponse(code=400, message=f"参数不完整，允许字段: {ALLOWED_FIELDS}", trace_id=uuid.uuid4().hex[:8])

    # 双重防御：正则校验字段名只含字母和下划线
    if not re.match(r'^[a-zA-Z_]+$', field):
        return ApiResponse(code=400, message="字段名不合法", trace_id=uuid.uuid4().hex[:8])

    col = _COLUMN_MAP[field]
    await db.execute(text(f"UPDATE sys_user SET {col}=:v, update_time=NOW() WHERE id=:c"), {"v": value, "c": customer_id})
    await db.commit()
    return ApiResponse(code=200, message="更新成功", data={"customer_id": customer_id, "field": field}, trace_id=uuid.uuid4().hex[:8])
