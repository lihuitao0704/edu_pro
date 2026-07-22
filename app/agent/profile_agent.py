"""画像 Agent — 信息抽取 + 标签生成 + 画像研判"""

from sqlalchemy.ext.asyncio import AsyncSession
from app.agent.base_agent import BaseAgent
from app.service.profile_service import ProfileService
from app.tool.profile_tool import ProfileTool


class ProfileAgent(BaseAgent):
    """用户画像 Agent"""

    def __init__(self, db: AsyncSession, session_id: str = ""):
        super().__init__(db, session_id)
        self.service = ProfileService(db)
        self.tool = ProfileTool(db)

    async def execute(self, message: str, **kwargs) -> dict:
        """
        执行画像相关操作
        支持意图：
        - "查询客户画像" → get_profile
        - "研判风险等级" → assess
        - "更新标签" → update_tags
        """
        customer_id = kwargs.get("customer_id")

        # 简单意图路由
        if "研判" in message or "评估" in message or "打分" in message:
            return await self._handle_assess(customer_id)
        elif "更新" in message or "标签" in message:
            tags = kwargs.get("tags", [])
            return await self._handle_update_tags(customer_id, tags)
        else:
            return await self._handle_query(customer_id)

    async def _handle_query(self, customer_id: int) -> dict:
        profile = await self.tool.get_profile(customer_id)
        if not profile:
            return {"reply": f"未找到客户 {customer_id} 的画像信息，请先创建画像", "profile": None}
        return {"reply": f"客户 {customer_id} 画像查询完成", "profile": profile}

    async def _handle_assess(self, customer_id: int) -> dict:
        result = await self.tool.assess(customer_id)
        reply = (
            f"客户 {customer_id} 风险研判完成。\n"
            f"风险等级：{result['risk_level']}\n"
            f"综合评分：{result['total_score']} 分\n"
            f"可购产品：{', '.join(result['recommended_products'])}"
        )
        if result.get("warnings"):
            reply += f"\n\n⚠️ 注意事项：{'; '.join(result['warnings'])}"
        return {"reply": reply, "profile": result}

    async def _handle_update_tags(self, customer_id: int, tags: list) -> dict:
        if not tags:
            return {"reply": "未提供标签数据", "updated": 0}
        result = await self.service.update_tags(customer_id, tags)
        return {"reply": f"已更新 {result['updated_tags']} 个标签", "updated": result["updated_tags"]}
