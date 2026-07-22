"""Profile Tool — 画像查询工具"""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.service.profile_service import ProfileService


class ProfileTool:
    """客户画像查询工具（供 Agent 调用）"""

    def __init__(self, db: AsyncSession):
        self.service = ProfileService(db)

    async def get_profile(self, customer_id: int) -> Optional[dict]:
        """获取客户画像"""
        profile = await self.service.get_profile(customer_id)
        if not profile:
            return None

        return {
            "customer_id": profile.customer_id,
            "risk_level": profile.risk_level,
            "risk_score": profile.risk_score,
            "confidence_score": str(profile.confidence_score) if profile.confidence_score else None,
            "total_assets": str(profile.total_assets) if profile.total_assets else None,
            "investment_experience": profile.investment_experience,
            "annual_income_range": profile.annual_income_range,
        }

    async def assess(self, customer_id: int) -> dict:
        """执行画像研判"""
        result = await self.service.assess(customer_id)
        return result.model_dump()
