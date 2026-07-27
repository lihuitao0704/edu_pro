"""投顾对话 API 路由 — LLM Agent 统一驱动

决策者从「开发者的 if/elif」变为「LLM 大模型」。
API 层只做一件事：创建 AdvisorAgent → 调用 execute / stream_execute → 返回结果。
Agent 内部自行决定调用哪个工具、按什么顺序调用。
"""

import json as _json

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.agent.advisor_agent import AdvisorAgent
from app.service.advisor_service import AdvisorService
from app.service.advisor_narrative_service import AdvisorNarrativeService
from app.model.schemas import AdvisorChatRequest, RecommendRequest, AllocationRequest
from app.utils.response import success, error
from app.utils.logger import get_logger
from app.utils.sse import stream_chat_result
from app.config.settings import get_settings
from app.security.authorization import (
    authenticated_actor_id,
    enforce_customer_scope,
    require_roles,
)
from sse_starlette.sse import EventSourceResponse

logger = get_logger(__name__)
router = APIRouter()
_settings = get_settings()


@router.post("/advisor")
async def advisor_chat(
    req: AdvisorChatRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "管理员")),
):
    """
    投顾对话接口（LLM Agent 驱动）

    接收用户自然语言消息 → 交给 AdvisorAgent → Agent 自行决策工具调用链 → 返回回复。

    Agent 工具箱：
      - profile_tool       → 查客户风险画像
      - recommend_products → 产品推荐打分
      - asset_allocation   → 资产配置建议
      - graphrag_search    → 知识图谱 + 文档检索
    """
    if not req.customer_id:
        return error(400, "缺少 customer_id 参数")

    enforce_customer_scope(user, req.customer_id)

    try:
        agent = AdvisorAgent(
            db, req.session_id, actor_id=authenticated_actor_id(user)
        )
        result = await agent.execute(
            req.message,
            customer_id=req.customer_id,
            audience_role=str(user.get("role") or ""),
        )
        raw_reply = result.get("reply", "")
        narrative = AdvisorNarrativeService.ensure_disclaimer(raw_reply) if raw_reply else AdvisorNarrativeService.render_template(result)

        return success(data={
            "reply": narrative,
            "narrative": narrative,
            "narrative_source": "llm" if raw_reply else "template",
            "recommendations": result.get("recommendations", []),
            "customer_profile": result.get("customer_profile"),
            "reasoning": result.get("reasoning"),
            "session_id": req.session_id,
        })
    except Exception as e:
        logger.error(f"投顾对话异常: {e}", exc_info=True)
        return error(500, f"投顾服务异常: {str(e)}")


@router.post("/advisor/stream")
async def advisor_chat_stream(
    req: AdvisorChatRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "管理员")),
):
    """
    投顾对话 SSE 真流式 — LLM token 级实时输出。

    事件契约（与 /api/chat/stream/v2 一致）：
      event: meta     → {agent: "advisor", session_id}
      event: token    → {content: "为"}           # LLM 逐 token / 模板逐字
      event: tool_end → {name: "smart_recommend"}
      event: done     → {reply, recommendations, allocation, session_id, ...}
      event: error    → {message}
    """
    if not req.customer_id:
        return error(400, "缺少 customer_id 参数")
    enforce_customer_scope(user, req.customer_id)

    agent = AdvisorAgent(
        db, req.session_id, actor_id=authenticated_actor_id(user)
    )
    audience_role = str(user.get("role") or "")

    async def event_generator():
        try:
            async for evt in agent.stream_execute(
                req.message,
                customer_id=req.customer_id,
                audience_role=audience_role,
            ):
                evt_type = evt.pop("type", "message")
                safe = _make_json_safe(evt)
                yield {
                    "event": evt_type,
                    "data": _json.dumps(safe, ensure_ascii=False, default=str),
                }
        except Exception as e:
            logger.error(f"投顾流式异常: {e}", exc_info=True)
            yield {
                "event": "error",
                "data": _json.dumps(
                    {"message": "当前智能投顾服务繁忙，请稍后重试。"},
                    ensure_ascii=False,
                ),
            }

    return EventSourceResponse(event_generator())


@router.post("/recommend")
async def recommend_products(
    req: RecommendRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "管理员")),
):
    """纯产品推荐接口（直接调用 Agent，不走会话）"""
    enforce_customer_scope(user, req.customer_id)
    agent = AdvisorAgent(db)
    result = await agent.execute(
        "推荐产品",
        customer_id=req.customer_id,
        audience_role=str(user.get("role") or ""),
    )
    return success(data=result)


@router.put("/advisor/recommendations/{recommendation_id}/feedback")
async def recommendation_feedback(
    recommendation_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "管理员")),
):
    """Record a recommendation outcome and feed it back into the customer profile."""
    customer_id = body.get("customer_id")
    if not customer_id:
        return error(400, "缺少 customer_id")
    enforce_customer_scope(user, customer_id)
    try:
        service = AdvisorService(db)
        record = await service.record_recommendation_feedback(
            int(customer_id), recommendation_id, str(body.get("status", "")), str(body.get("reason", ""))
        )
        if not record:
            return error(404, "推荐记录不存在或不属于该客户")
        await db.commit()
        return success(data={"recommendation_id": record.id, "status": record.status}, message="反馈已记录")
    except ValueError as exc:
        return error(400, str(exc))
    except Exception as exc:
        await db.rollback()
        logger.error("推荐反馈记录失败: %s", exc, exc_info=True)
        return error(500, "推荐反馈保存失败")


@router.post("/advisor/allocation")
async def asset_allocation(
    req: AllocationRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "管理员")),
):
    """资产配置建议接口（直接调用 Agent，不走会话）"""
    enforce_customer_scope(user, req.customer_id)
    agent = AdvisorAgent(db)
    result = await agent.execute("资产配置", customer_id=req.customer_id)
    return success(data=result)


@router.post("/advisor/holdings-analysis")
async def holdings_analysis(
    req: AllocationRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "管理员")),
):
    """Analyze one explicitly scoped customer's holdings through AdvisorAgent."""
    enforce_customer_scope(user, req.customer_id)
    agent = AdvisorAgent(db)
    result = await agent.execute("分析持仓", customer_id=req.customer_id)
    return success(data=result)


def _make_json_safe(obj: dict) -> dict:
    """递归清理 dict，将 Pydantic 模型转为普通 dict，确保 JSON 可序列化"""
    result = {}
    for k, v in obj.items():
        if hasattr(v, "model_dump"):
            result[k] = v.model_dump()
        elif isinstance(v, dict):
            result[k] = _make_json_safe(v)
        elif isinstance(v, list):
            result[k] = [
                x.model_dump() if hasattr(x, "model_dump") else x for x in v
            ]
        else:
            result[k] = v
    return result
