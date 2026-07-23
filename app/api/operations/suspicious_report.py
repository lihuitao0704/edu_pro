"""业务操作 API — 可疑上报"""
import json
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.model.schemas import ApiResponse
from app.security.authorization import authenticated_actor_id, require_roles

router = APIRouter()


@router.post("/suspicious")
async def report_suspicious(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("风控专员", "管理员")),
) -> ApiResponse:
    """可疑交易上报"""
    customer_id = body.get("customer_id")
    reason = body.get("reason", "")
    reporter_id = authenticated_actor_id(user, body.get("reporter_id"))

    if not customer_id or not reason:
        return ApiResponse(code=400, message="缺少客户ID或原因", trace_id=uuid.uuid4().hex[:8])

    alert_no = f"ALT{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
    # 将 alert_no 持久化到 transaction_ids JSON 字段中，确保后续可查询
    tx_ids_json = json.dumps({"alert_no": alert_no, "reporter_id": reporter_id}, ensure_ascii=False)
    await db.execute(
        text("INSERT INTO fin_risk_alert (customer_id,alert_type,alert_level,trigger_detail,transaction_ids,status,create_time) VALUES (:c,'suspicious','medium',:d,:tids,'待处理',NOW())"),
        {"c": customer_id, "d": reason, "tids": tx_ids_json},
    )
    await db.commit()
    return ApiResponse(code=200, message="上报成功", data={"customer_id": customer_id, "alert_no": alert_no}, trace_id=uuid.uuid4().hex[:8])
