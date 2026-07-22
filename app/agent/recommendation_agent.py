"""推荐 Agent — 产品筛选 + 排序 + 推荐"""

from sqlalchemy.ext.asyncio import AsyncSession
from app.agent.base_agent import BaseAgent
from app.tool.recommendation_tool import RecommendationTool
from app.tool.allocation_tool import AllocationTool


class RecommendationAgent(BaseAgent):
    """产品推荐 Agent"""

    def __init__(self, db: AsyncSession, session_id: str = ""):
        super().__init__(db, session_id)
        self.recommend_tool = RecommendationTool(db)
        self.allocation_tool = AllocationTool(db)

    async def execute(self, message: str, **kwargs) -> dict:
        customer_id = kwargs.get("customer_id")
        top_n = kwargs.get("top_n", 3)

        if not customer_id:
            return {"reply": "请指定客户ID", "recommendations": []}

        # 意图路由
        if "配置" in message or "资产配置" in message:
            return await self._handle_allocation(customer_id)
        else:
            return await self._handle_recommend(customer_id, top_n)

    async def _handle_recommend(self, customer_id: int, top_n: int) -> dict:
        result = await self.recommend_tool.recommend(customer_id, top_n)

        recs = result.get("recommendations", [])
        if not recs:
            return {"reply": result.get("reasoning", "暂无推荐"), "recommendations": []}

        reply = "为您推荐以下产品：\n\n"
        for i, r in enumerate(recs, 1):
            reply += f"{i}. {r.product_name} ({r.risk_level}级) — 预期年化 {r.expected_return}%\n"
            reply += f"   推荐理由：{r.reason}\n\n"

        reply += f"\n{result.get('reasoning', '')}"
        return {
            "reply": reply,
            "recommendations": [r.model_dump() for r in recs],
            "customer_profile": result.get("customer_profile"),
            "reasoning": result.get("reasoning"),
        }

    async def _handle_allocation(self, customer_id: int) -> dict:
        result = await self.allocation_tool.get_allocation(customer_id)

        alloc = result.get("allocation", {})
        reply = f"根据您的 {result['risk_level']} 风险等级，建议资产配置：\n"
        for asset_type, pct in alloc.items():
            reply += f"  {asset_type}: {pct}%\n"
        reply += f"\n说明：{result['explanation']}"

        return {"reply": reply, "allocation": alloc, "risk_level": result["risk_level"]}
