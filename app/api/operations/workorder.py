"""业务操作 API — 工单创建"""
import uuid
import json
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.model.schemas import ApiResponse

router = APIRouter()


@router.post("/workorder")
async def create_work_order(body: dict, db: AsyncSession = Depends(get_db)) -> ApiResponse:
    """创建业务工单"""
    customer_id = body.get("customer_id")
    order_type = body.get("order_type", "咨询")
    content = body.get("content", "")
    submitter_id = body.get("submitter_id")

    if not customer_id or not content:
        return ApiResponse(code=400, message="缺少客户ID或内容", trace_id=uuid.uuid4().hex[:8])

    wo_no = f"WO{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"
    biz_json = json.dumps({"content": content}, ensure_ascii=False)
    await db.execute(
        text("INSERT INTO biz_work_order (work_order_no,order_type,customer_id,submitter_id,status,remark,biz_content,create_time) VALUES (:n,:t,:c,:s,'待处理',:r,:b,NOW())"),
        {"n": wo_no, "t": order_type, "c": customer_id, "s": submitter_id, "r": content, "b": biz_json},
    )
    await db.commit()
    return ApiResponse(code=200, message="工单创建成功", data={"work_order_no": wo_no, "order_type": order_type}, trace_id=uuid.uuid4().hex[:8])
