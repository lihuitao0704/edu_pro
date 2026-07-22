"""解释 Agent — 推荐理由生成 + 风险等级解读 + 画像摘要"""

from sqlalchemy.ext.asyncio import AsyncSession
from app.agent.base_agent import BaseAgent
from app.service.profile_service import ProfileService


class ExplanationAgent(BaseAgent):
    """解释与说明 Agent"""

    def __init__(self, db: AsyncSession, session_id: str = ""):
        super().__init__(db, session_id)
        self.profile_service = ProfileService(db)

    async def execute(self, message: str, **kwargs) -> dict:
        customer_id = kwargs.get("customer_id")

        if not customer_id:
            return {"reply": "请指定客户ID"}

        # 获取画像
        profile = await self.profile_service.get_profile(customer_id)
        if not profile:
            return {"reply": f"客户 {customer_id} 画像不存在"}

        # 获取最近研判评分明细
        rating_history = await self.profile_service.long_term.get_rating_history(customer_id, limit=1)

        if "风险" in message or "等级" in message:
            return self._explain_risk_level(profile, rating_history)
        elif "推荐" in message or "为什么" in message:
            return self._explain_recommendation(profile, kwargs.get("recommendations", []))
        else:
            return self._explain_summary(profile, rating_history)

    def _explain_risk_level(self, profile, rating_history) -> dict:
        latest = rating_history[0] if rating_history else None

        reply = f"【风险等级解读】\n"
        reply += f"客户等级：{profile.risk_level}\n"
        reply += f"综合评分：{profile.risk_score} 分\n\n"

        if latest:
            reply += "评分明细：\n"
            reply += f"  基础属性：{latest.basic_score} 分\n"
            reply += f"  投资经验：{latest.experience_score} 分\n"
            reply += f"  风险偏好：{latest.risk_pref_score} 分\n"
            reply += f"  行为异常：{latest.behavior_score} 分\n"

        return {"reply": reply, "risk_level": profile.risk_level}

    def _explain_recommendation(self, profile, recommendations: list) -> dict:
        reply = f"根据客户 {profile.risk_level} 风险等级，推荐理由如下：\n\n"
        for i, r in enumerate(recommendations[:3], 1):
            reply += f"{i}. {r.get('product_name', '未知产品')}: {r.get('reason', '匹配客户风险偏好')}\n"

        return {"reply": reply}

    def _explain_summary(self, profile, rating_history) -> dict:
        reply = (
            f"客户画像摘要：\n"
            f"  风险等级：{profile.risk_level}\n"
            f"  综合评分：{profile.risk_score} 分\n"
            f"  资产规模：{profile.total_assets} 元\n"
            f"  投资经验：{profile.investment_experience or '暂无'}\n"
            f"  收入范围：{profile.annual_income_range or '暂无'}\n"
        )
        return {"reply": reply}
