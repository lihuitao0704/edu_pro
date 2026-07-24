from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common_services.analytics_service.analytics_service import ChatAnalyticsService
from app.config.database import get_db
from app.model.entities import FinAgentTrace, FinChatMetricDaily, FinChatSession
from app.security.authorization import authenticated_actor_id, require_roles
from app.utils.response import success

router = APIRouter()


@router.get("/analytics/chat/stats", response_model=dict)
async def chat_stats(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("管理员")),
):
    rows = (await db.execute(select(FinChatMetricDaily))).scalars().all()
    today_start = datetime.combine(date.today(), time.min)
    today_sessions = (await db.execute(
        select(func.count()).select_from(FinChatSession).where(FinChatSession.create_time >= today_start)
    )).scalar_one()
    return success(data=ChatAnalyticsService.aggregate(rows, int(today_sessions or 0)))


@router.get("/analytics/chat/traces", response_model=dict)
async def list_traces(
    session_id: str = "", agent_name: str = "", status: str = "",
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "客户经理", "风控专员", "管理员")),
):
    statement = select(FinAgentTrace)
    if str(user.get("role")) != "管理员":
        statement = statement.where(FinAgentTrace.user_id == authenticated_actor_id(user))
    if session_id:
        statement = statement.where(FinAgentTrace.session_id == session_id)
    if agent_name:
        statement = statement.where(FinAgentTrace.target_agent == agent_name)
    if status:
        statement = statement.where(FinAgentTrace.status == status)
    traces = (await db.execute(statement.order_by(FinAgentTrace.created_time.desc()).limit(100))).scalars().all()
    return success(data={"items": [{
        "trace_id": item.trace_id, "session_id": item.session_id,
        "agent_name": item.target_agent, "status": item.status,
        "created_time": item.created_time.isoformat() if item.created_time else None,
    } for item in traces]})


@router.get("/analytics/chat/traces/{trace_id}", response_model=dict)
async def get_trace(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "客户经理", "风控专员", "管理员")),
):
    trace = await db.get(FinAgentTrace, trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    if str(user.get("role")) != "管理员" and int(trace.user_id) != authenticated_actor_id(user):
        raise HTTPException(status_code=403, detail="cannot access another user's trace")
    return success(data={
        "trace_id": trace.trace_id, "session_id": trace.session_id,
        "intent": trace.intent, "agent_name": trace.target_agent,
        "status": trace.status, "input_masked": trace.input_masked,
        "output_masked": trace.output_masked,
        "created_time": trace.created_time.isoformat() if trace.created_time else None,
    })
