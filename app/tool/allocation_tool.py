"""Allocation Tool — 资产配置建议工具"""

from sqlalchemy.ext.asyncio import AsyncSession
from app.service.advisor_service import AdvisorService


class AllocationTool:
    """资产配置工具（供 Agent 调用）"""

    def __init__(self, db: AsyncSession):
        self.advisor_service = AdvisorService(db)

    async def get_allocation(self, customer_id: int) -> dict:
        """获取资产配置建议"""
        result = await self.advisor_service.get_allocation(customer_id)
        return result.model_dump()
