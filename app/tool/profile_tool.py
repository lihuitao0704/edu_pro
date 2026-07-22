"""
Profile Tool — 客户风险画像查询工具（LangChain BaseTool）
供 Agent 调用：输入 customer_id，返回完整风险画像 JSON
"""

from typing import Optional, Type
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from langchain_core.tools import BaseTool

from app.model.entities import SysUser, FinCustomerProfile
from app.service.profile_service import ProfileService


class ProfileToolInput(BaseModel):
    """Profile Tool 的输入 Schema"""
    customer_id: int = Field(description="客户ID（sys_user 表中的 id）")


class ProfileTool(BaseTool):
    """
    客户风险画像查询工具

    当用户询问某位客户的风险等级、投资画像、风险评分时调用此工具。
    内部执行完整研判流程（数据收集 → 熔断检查 → 四维度打分 → 等级判定），
    返回结构化的 JSON 画像结果。
    """

    name: str = "profile_tool"
    description: str = (
        "查询客户的风险画像信息。"
        "输入客户ID（整数），返回该客户的完整风险画像 JSON，包含："
        "基本信息（姓名、年龄、学历、职业）、"
        "四维度得分明细（基础属性、投资经验、风险偏好、行为异常）、"
        "综合评分、风险等级（C1-C5）、"
        "熔断规则触发情况、可购产品列表。"
        '当用户要求「评估风险」「查看风险等级」「分析画像」时调用此工具。'
    )
    args_schema: Type[BaseModel] = ProfileToolInput

    # --- 非 Pydantic 字段（不会被序列化） ---
    db: AsyncSession = Field(exclude=True)

    def __init__(self, db: AsyncSession, **kwargs):
        super().__init__(db=db, **kwargs)

    async def _arun(self, customer_id: int) -> str:
        """
        异步执行画像查询并返回 JSON 字符串。

        流程:
        1. 调用 ProfileService.assess() 执行完整研判（引擎层打分）
        2. 查询 SysUser 获取自然人信息
        3. 组装为 LLM 友好的结构化 JSON
        """
        service = ProfileService(self.db)

        # ── Step 1: 执行完整研判 ──
        try:
            assess_result = await service.assess(customer_id, trigger_type="agent_query")
        except Exception as e:
            return self._error_json(customer_id, str(e))

        # ── Step 2: 查询客户自然人信息 ──
        user_stmt = select(SysUser).where(SysUser.id == customer_id)
        user_result = await self.db.execute(user_stmt)
        user = user_result.scalar_one_or_none()

        profile_stmt = select(FinCustomerProfile).where(FinCustomerProfile.customer_id == customer_id)
        profile_result = await self.db.execute(profile_stmt)
        profile = profile_result.scalar_one_or_none()

        # ── Step 3: 组装 LLM 友好的 JSON ──
        return self._build_json(customer_id, user, profile, assess_result)

    def _run(self, customer_id: int) -> str:
        """同步入口（未使用，保留抽象方法实现）"""
        raise NotImplementedError("ProfileTool 仅支持异步调用，请使用 _arun")

    # ═══════════════════════════════════════════════════════════════
    # 内部组装方法
    # ═══════════════════════════════════════════════════════════════

    def _build_json(self, customer_id: int, user, profile, assess_result) -> str:
        """将研判结果 + 用户信息组装为 LLM 可读的 JSON 字符串"""
        import json

        dims = assess_result.dimensions

        payload = {
            "customer_id": customer_id,
            "basic_info": {
                "name": user.real_name if user else "未知",
                "age": user.age if user else None,
                "education": user.education if user else None,
                "occupation": user.occupation if user else None,
                "annual_income_range": profile.annual_income_range if profile else None,
                "total_assets": str(profile.total_assets) if (profile and profile.total_assets) else None,
                "investment_experience": profile.investment_experience if profile else None,
            },
            "assessment": {
                "risk_level": assess_result.risk_level,
                "risk_level_name": self._level_to_name(assess_result.risk_level),
                "total_score": assess_result.total_score,
                "confidence_score": assess_result.confidence_score,
            },
            "dimensions": {
                "basic": {
                    "label": "维度一：基础属性特征",
                    "full_score": 25,
                    "score": dims["basic"].score,
                    "detail": dims["basic"].detail.model_dump() if dims["basic"].detail else None,
                    "interpretation": self._interpret_basic(dims["basic"].score, dims["basic"].detail),
                },
                "experience": {
                    "label": "维度二：投资经验特征",
                    "full_score": 25,
                    "score": dims["experience"].score,
                    "detail": dims["experience"].detail.model_dump() if dims["experience"].detail else None,
                    "interpretation": self._interpret_experience(dims["experience"].score, dims["experience"].detail),
                },
                "risk_pref": {
                    "label": "维度三：风险偏好特征",
                    "full_score": 30,
                    "score": dims["risk_pref"].score,
                    "detail": dims["risk_pref"].detail.model_dump() if dims["risk_pref"].detail else None,
                    "interpretation": self._interpret_risk_pref(dims["risk_pref"].score, dims["risk_pref"].detail),
                },
                "behavior": {
                    "label": "维度四：行为异常特征",
                    "full_score": 20,
                    "score": dims["behavior"].score,
                    "detail": dims["behavior"].detail.model_dump() if dims["behavior"].detail else None,
                    "interpretation": self._interpret_behavior(dims["behavior"].score, dims["behavior"].detail),
                },
            },
            "circuit_breakers": assess_result.circuit_breakers,
            "warnings": assess_result.warnings,
            "recommended_products": assess_result.recommended_products,
        }

        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _error_json(self, customer_id: int, error_msg: str) -> str:
        import json
        return json.dumps({
            "customer_id": customer_id,
            "error": True,
            "message": f"画像查询失败：{error_msg}",
        }, ensure_ascii=False)

    # ═══════════════════════════════════════════════════════════════
    # 维度通俗解读（为 LLM 提供上下文线索）
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _level_to_name(level: str) -> str:
        mapping = {"C1": "保守型", "C2": "稳健型", "C3": "平衡型", "C4": "进取型", "C5": "激进型"}
        return mapping.get(level, level)

    @staticmethod
    def _interpret_basic(score: float, detail) -> str:
        """对基础属性维度的通俗解释"""
        if score >= 20:
            return "基础条件优秀：年龄适中、高学历、高收入、资产雄厚，具备较强的风险承受基础。"
        elif score >= 15:
            return "基础条件良好：整体财务状况稳定，具备一定的风险承受能力。"
        elif score >= 10:
            return "基础条件一般：收入或资产中等，需审慎评估可承受的风险水平。"
        else:
            return "基础条件偏弱：收入较低或资产有限，建议优先配置低风险产品。"

    @staticmethod
    def _interpret_experience(score: float, detail) -> str:
        if score >= 20:
            return "投资经验丰富：长期接触多种产品，对市场波动有充分认知。"
        elif score >= 15:
            return "有一定投资经验：了解常见金融产品，能理解市场基本波动。"
        elif score >= 10:
            return "投资经验较少：建议从低风险产品入手，逐步积累经验。"
        else:
            return "几乎无投资经验：强烈建议以保本类产品为主，谨慎尝试风险投资。"

    @staticmethod
    def _interpret_risk_pref(score: float, detail) -> str:
        if score >= 25:
            return "风险偏好较高：愿意承受较大波动以追求高收益。"
        elif score >= 18:
            return "风险偏好中等偏高：能接受一定波动，但仍有底线。"
        elif score >= 12:
            return "风险偏好中等：追求稳健增值，不愿承受过大波动。"
        else:
            return "风险偏好保守：以保本为先，厌恶亏损。"

    @staticmethod
    def _interpret_behavior(score: float, detail) -> str:
        if score >= 18:
            return "交易行为正常，无异常操作记录。"
        elif score >= 12:
            return "存在轻微异常行为（如频繁赎回或非正常时段交易），需关注。"
        elif score >= 5:
            return "存在多项中等风险异常行为，建议人工复核交易记录。"
        else:
            return "存在高风险异常行为，已触发风控预警，需立即核查。"
