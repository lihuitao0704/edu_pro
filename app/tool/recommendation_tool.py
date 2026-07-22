"""Recommendation Tool — 产品推荐打分工具"""

from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from app.service.advisor_service import AdvisorService


class RecommendationTool:
    """产品推荐工具（供 Agent 调用）"""

    def __init__(self, db: AsyncSession):
        self.advisor_service = AdvisorService(db)

    async def recommend(self, customer_id: int, top_n: int = 3) -> dict:
        """推荐产品"""
        return await self.advisor_service.recommend_products(customer_id, top_n)
