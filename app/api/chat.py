"""
Chat API — 智能客服对话接口
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.model.schemas import CustomerChatRequest, CustomerChatResponse
from app.service.agent_service import get_customer_service_agent
from app.utils.response import success

router = APIRouter()


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
