"""
Chat API — 智能客服对话 + 数据分析 Agent + 业务操作对话接口
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
from app.config.database import get_db
from app.model.schemas import (
    CustomerChatRequest, CustomerChatResponse,
    QueryRequest, QueryResponse, ApiResponse,
)
from app.agent.customer_agent import get_customer_service_agent
from app.service.nl2sql_service import NL2SQLService
from app.agent.operator_agent import operator_chat
from app.security.authorization import (
    enforce_customer_scope,
    get_request_role,
    require_roles,
)
from app.utils.response import success, error
from app.utils.sse import stream_chat_result
from app.config.settings import get_settings
from sse_starlette.sse import EventSourceResponse

# 智能客服路由（/api/chat/customer）
customer_router = APIRouter()

# 业务操作路由（/api/chat/operator）
operator_router = APIRouter()

# 向后兼容：保留 router 引用（指向客服路由，避免其他模块 import 报错）
router = customer_router
_settings = get_settings()


# ==================== 智能客服 ====================


class OperatorChatRequest(BaseModel):
    """业务操作对话请求"""
    message: str
    session_id: str = ""
    user_id: int = 0
    user_role: str = "理财顾问"


class OperatorChatResponse(BaseModel):
    """业务操作对话响应"""
    reply: str
    action: Optional[str] = None
    params: dict = {}
    status: str = "ok"
    session_id: str = ""


@customer_router.post("/customer", response_model=dict)
async def customer_chat(
    request: CustomerChatRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(
        require_roles("客户", "理财顾问", "客户经理", "风控专员", "管理员")
    ),
):
    enforce_customer_scope(user, request.user_id)
    """
    智能客服对话接口

    处理用户消息，返回 AI 回复
    """
    agent = get_customer_service_agent(db)
    response = await agent.handle(
        session_id=request.session_id,
        user_id=request.user_id,
        message=request.message,
    )

    return success(data=response.model_dump())


@customer_router.post("/customer/stream")
async def customer_chat_stream(
    request: CustomerChatRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(
        require_roles("客户", "理财顾问", "客户经理", "风控专员", "管理员")
    ),
):
    """SSE 客服对话，事件顺序为 meta → delta* → sources? → done。"""
    enforce_customer_scope(user, request.user_id)
    agent = get_customer_service_agent(db)
    response = await agent.handle(
        session_id=request.session_id,
        user_id=request.user_id,
        message=request.message,
    )
    data = response.model_dump()
    data["agent_type"] = "customer_service"
    return EventSourceResponse(
        stream_chat_result(data, chunk_size=_settings.sse.chunk_size)
    )


@operator_router.post("/operator")
async def chat_operator(body: OperatorChatRequest, request: Request) -> dict:
    """
    业务操作 Agent 对话接口
    POST /api/chat/operator
    """
    authenticated_user = getattr(request.state, "user", None) or {}
    try:
        result = await operator_chat(
            message=body.message,
            session_id=body.session_id,
            user_id=int(authenticated_user.get("user_id") or 0),
            user_role=get_request_role(request),
        )
        return success(data=result)
    except Exception as e:
        return error(code=500, message=f"业务操作处理异常: {e}")


# ==================== 数据分析 Agent ====================

# 数据分析Agent使用独立的路由器，避免与智能客服路由混淆
analyst_router = APIRouter()
nl2sql_service = NL2SQLService()


@analyst_router.post("/analyst", response_model=ApiResponse, tags=["数据分析Agent"])
async def chat_analyst(
    request: QueryRequest,
    _: dict = Depends(
        require_roles("理财顾问", "客户经理", "风控专员", "管理员")
    ),
):
    """
    数据分析Agent对话接口

    支持自然语言查询业务数据，自动生成SQL并返回结果。
    """
    try:
        result = nl2sql_service.query_and_explain(request.message, user_id=request.user_id)

        if result.get("success"):
            return success(
                data={
                    "reply": result.get("explanation"),
                    "sql": result.get("sql"),
                    "query_result": result.get("query_result"),
                    "session_id": request.session_id,
                    "safety": result.get("safety"),
                    "truncated": result.get("truncated", False),
                    "rejected": result.get("rejected", False),
                    "reject_reason": result.get("reject_reason"),
                    "timing": result.get("timing"),
                },
                message="查询成功",
            )
        else:
            return error(
                code=1003,
                message=result.get("error", "查询失败"),
                data={
                    "sql": result.get("sql"),
                    "session_id": request.session_id,
                    "safety": result.get("safety"),
                    "rejected": result.get("rejected", False),
                    "reject_reason": result.get("reject_reason"),
                },
            )
    except Exception as e:
        return error(
            code=500,
            message=f"服务异常: {str(e)}",
        )


@analyst_router.post("/analyst/execute", response_model=ApiResponse, tags=["数据分析Agent"])
async def analyst_execute(
    request: QueryRequest,
    _: dict = Depends(
        require_roles("理财顾问", "客户经理", "风控专员", "管理员")
    ),
):
    """
    直接执行 SQL（跳过生成）— 用于用户编辑 SQL 后重新查询。
    """
    try:
        sql = request.message  # message 字段承载 SQL 文本
        valid, msg = nl2sql_service.validate_sql(sql)
        if not valid:
            return error(
                code=1003,
                message=msg,
                data={
                    "sql": sql,
                    "session_id": request.session_id,
                    "safety": {"select_only": False, "row_limit": True, "no_sensitive": False},
                },
            )

        exec_result = nl2sql_service.execute_sql(sql)
        if "error" in exec_result:
            return error(
                code=1004,
                message=exec_result["error"],
                data={
                    "sql": sql,
                    "session_id": request.session_id,
                    "safety": {"select_only": True, "row_limit": True, "no_sensitive": True},
                },
            )

        explanation = nl2sql_service.llm.explain_result(request.message, exec_result["rows"])
        exceeded = exec_result.get("row_count", 0) >= _settings.nl2sql.max_rows

        return success(
            data={
                "reply": explanation,
                "sql": sql,
                "query_result": exec_result["rows"],
                "session_id": request.session_id,
                "safety": {"select_only": True, "row_limit": not exceeded, "no_sensitive": True},
                "truncated": exceeded,
            },
            message="执行成功",
        )
    except Exception as e:
        return error(
            code=500,
            message=f"执行异常: {str(e)}",
        )


@analyst_router.get("/analyst/session/{session_id}/history", tags=["数据分析Agent"])
async def get_session_history(
    session_id: str,
    _: dict = Depends(
        require_roles("理财顾问", "客户经理", "风控专员", "管理员")
    ),
):
    """获取会话历史（预留接口）"""
    return success(
        data={
            "session_id": session_id,
            "messages": [],
        },
        message="获取成功",
    )
