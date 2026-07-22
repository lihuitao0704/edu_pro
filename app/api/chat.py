"""
统一对话入口 — agent_type 路由
负责人: LHG（operator 部分）
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from app.service.operator_agent import operator_chat

router = APIRouter()


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


@router.post("/operator")
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
