"""业务操作 API — 工单创建、查询与处理"""
import uuid
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.model.schemas import ApiResponse
from app.security.authorization import authenticated_actor_id, require_roles
from app.service.risk_monitor_service import RiskMonitorService
from app.utils.response import success

router = APIRouter()
WORK_ORDER_ROLES = ("客户经理", "风控专员", "管理员")


@router.post("/workorder")
async def create_work_order(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles(*WORK_ORDER_ROLES)),
) -> ApiResponse:
    """创建业务工单"""
    customer_id = body.get("customer_id")
    order_type = body.get("order_type", "咨询")
    content = body.get("content", "")
    submitter_id = authenticated_actor_id(user, body.get("submitter_id"))

    if not customer_id or not content:
        return ApiResponse(code=400, message="缺少客户ID或内容", trace_id=uuid.uuid4().hex[:8])

    wo_no = f"WO{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
    biz_json = json.dumps({"content": content}, ensure_ascii=False)
    await db.execute(
        text("INSERT INTO biz_work_order (work_order_no,order_type,customer_id,submitter_id,status,remark,biz_content,create_time) VALUES (:n,:t,:c,:s,'待处理',:r,:b,NOW())"),
        {"n": wo_no, "t": order_type, "c": customer_id, "s": submitter_id, "r": content, "b": biz_json},
    )
    await db.commit()
    return ApiResponse(code=200, message="工单创建成功", data={"work_order_no": wo_no, "order_type": order_type}, trace_id=uuid.uuid4().hex[:8])


@router.get("/workorders")
async def list_work_orders(
    status: str = "",
    customer_id: int = 0,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_roles(*WORK_ORDER_ROLES)),
):
    filters = ["1=1"]
    params = {
        "offset": (max(page, 1) - 1) * page_size,
        "limit": min(max(page_size, 1), 100),
    }
    if status:
        filters.append("status = :status")
        params["status"] = status
    if customer_id:
        filters.append("customer_id = :customer_id")
        params["customer_id"] = customer_id
    where = " AND ".join(filters)
    total_result = await db.execute(
        text(f"SELECT COUNT(*) FROM biz_work_order WHERE {where}"), params
    )
    result = await db.execute(
        text(
            "SELECT id, work_order_no, order_type, sub_type, customer_id, "
            "submitter_id, handler_id, current_node, priority, status, "
            "biz_content, remark, create_time, update_time "
            f"FROM biz_work_order WHERE {where} ORDER BY create_time DESC "
            "LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    return success(
        data={
            "items": [_work_order_dict(row) for row in result.mappings().all()],
            "total": int(total_result.scalar() or 0),
            "page": max(page, 1),
            "page_size": params["limit"],
        }
    )


@router.get("/workorder/{work_order_id}")
async def get_work_order(
    work_order_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_roles(*WORK_ORDER_ROLES)),
):
    result = await db.execute(
        text("SELECT * FROM biz_work_order WHERE id = :id"),
        {"id": work_order_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="工单不存在")
    return success(data=_work_order_dict(row))


@router.put("/workorder/{work_order_id}/handle")
async def handle_work_order(
    work_order_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles(*WORK_ORDER_ROLES)),
):
    status = body.get("status", "已完成")
    if status not in {"待处理", "处理中", "已完成", "已关闭"}:
        raise HTTPException(status_code=400, detail="工单状态无效")
    handler_id = authenticated_actor_id(user)
    detail_result = await db.execute(
        text("SELECT biz_content FROM biz_work_order WHERE id=:id"),
        {"id": work_order_id},
    )
    detail_row = detail_result.mappings().first()
    if not detail_row:
        raise HTTPException(status_code=404, detail="工单不存在")

    biz_content = detail_row.get("biz_content") or {}
    if isinstance(biz_content, str):
        try:
            biz_content = json.loads(biz_content)
        except json.JSONDecodeError:
            biz_content = {}

    result = await db.execute(
        text(
            "UPDATE biz_work_order SET status=:status, current_node=:node, "
            "handler_id=:handler_id, remark=:remark, update_time=NOW() WHERE id=:id"
        ),
        {
            "status": status,
            "node": "已关闭" if status in {"已完成", "已关闭"} else "处理中",
            "handler_id": handler_id,
            "remark": body.get("handle_note", ""),
            "id": work_order_id,
        },
    )
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="工单不存在")

    alert_id = biz_content.get("alert_id") if isinstance(biz_content, dict) else None
    if alert_id and status in {"处理中", "已完成", "已关闭"}:
        action = "resolved" if status in {"已完成", "已关闭"} else "processing"
        await RiskMonitorService().handle_alert(
            db,
            str(alert_id),
            action,
            handler_id,
            body.get("handle_note", ""),
        )
    return success(data={"work_order_id": work_order_id, "status": status})


def _work_order_dict(row) -> dict:
    data = dict(row)
    for key in ("create_time", "update_time"):
        if data.get(key):
            data[key] = data[key].isoformat()
    return data
