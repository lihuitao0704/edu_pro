"""
Chat API — 智能客服对话 + 数据分析 Agent + 业务操作对话接口
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
from app.config.database import get_db
from app.model.schemas import (
    CustomerChatRequest, CustomerChatResponse,
    QueryRequest, QueryResponse, ApiResponse,
)
from app.service.agent_service import get_customer_service_agent
from app.service.nl2sql_service import NL2SQLService
from app.service.operator_agent import operator_chat
from app.utils.response import success, error

# 智能客服路由（/api/chat/customer）
customer_router = APIRouter()

# 业务操作路由（/api/chat/operator）
operator_router = APIRouter()

# 向后兼容：保留 router 引用（指向客服路由，避免其他模块 import 报错）
router = customer_router


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
):
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


@operator_router.post("/operator")
async def chat_operator(body: OperatorChatRequest) -> OperatorChatResponse:
    """
    业务操作 Agent 对话接口
    POST /api/chat/operator
    """
    result = await operator_chat(
        message=body.message,
        session_id=body.session_id,
        user_id=body.user_id,
        user_role=body.user_role,
    )
    return OperatorChatResponse(**result)


# ==================== 数据分析 Agent ====================

# 数据分析Agent使用独立的路由器，避免与智能客服路由混淆
analyst_router = APIRouter()
nl2sql_service = NL2SQLService()


@analyst_router.post("/analyst", response_model=ApiResponse)
async def chat_analyst(request: QueryRequest):
    """
    数据分析Agent对话接口

    支持自然语言查询业务数据，自动生成SQL并返回结果。
    """
    try:
        result = nl2sql_service.query_and_explain(request.message)

        if result.get("success"):
            return success(
                data={
                    "reply": result.get("explanation"),
                    "sql": result.get("sql"),
                    "query_result": result.get("query_result"),
                    "session_id": request.session_id,
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
                },
            )
    except Exception as e:
        return error(
            code=500,
            message=f"服务异常: {str(e)}",
        )


@analyst_router.get("/session/{session_id}/history")
async def get_session_history(session_id: str):
    """获取会话历史（预留接口）"""
    return success(
        data={
            "session_id": session_id,
            "messages": [],
        },
        message="获取成功",
    )
