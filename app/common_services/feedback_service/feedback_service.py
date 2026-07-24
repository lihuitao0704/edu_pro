from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.entities import FinChatFeedback, FinChatSession


class FeedbackService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def submit(self, actor_id: int, session_id: str, rating: int, comment: str | None) -> dict:
        if rating < 1 or rating > 5:
            raise HTTPException(status_code=422, detail="rating must be between 1 and 5")
        session = await self.db.get(FinChatSession, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="chat session not found")
        if int(session.user_id) != actor_id:
            raise HTTPException(status_code=403, detail="cannot rate another user's session")
        low_rating_alert = rating <= 2
        if low_rating_alert:
            session.flagged = True
        self.db.add(FinChatFeedback(
            session_id=session_id,
            user_id=actor_id,
            rating=rating,
            comment=comment,
            intent=session.last_intent,
            agent_name=session.last_agent,
        ))
        await self.db.commit()
        return {
            "session_id": session_id,
            "rating": rating,
            "low_rating_alert": low_rating_alert,
        }
