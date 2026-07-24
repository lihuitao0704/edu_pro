from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common_services.feedback_service.feedback_service import FeedbackService
from app.config.database import get_db
from app.security.authorization import authenticated_actor_id, require_roles
from app.common_services.safety_guard.input_filter import InputSafetyFilter
from app.utils.response import success

router = APIRouter()


class FeedbackRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/chat/customer/feedback", response_model=dict)
async def submit_feedback(
    request: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "客户经理", "风控专员", "管理员")),
):
    decision = InputSafetyFilter().inspect(request.comment or "")
    if decision.blocked:
        return success(data={"accepted": False, "message": decision.user_message})
    result = await FeedbackService(db).submit(
        authenticated_actor_id(user), request.session_id, request.rating, decision.sanitized_text
    )
    return success(data=result)
