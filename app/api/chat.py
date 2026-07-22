"""
Chat API — 智能客服对话接口
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
from app.config.database import get_db
from app.model.schemas import CustomerChatRequest, CustomerChatResponse
from app.service.agent_service import get_customer_service_agent
from app.utils.response import success
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

@router.post("/customer", response_model=dict)
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
