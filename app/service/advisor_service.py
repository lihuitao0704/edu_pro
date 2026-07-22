"""
投顾推荐服务
产品推荐 + 资产配置
"""

from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.schemas import ProductRecommend, AllocationResult
from app.service.profile_service import ProfileService
from app.config.rules_config import (
    SUITABILITY_MATRIX, ASSET_ALLOCATION_TEMPLATES, RECOMMENDATION_WEIGHTS,
)


# Mock 产品数据（实际应从数据库获取）
MOCK_PRODUCTS = [
    {"product_code": "F100001", "product_name": "现金宝货币A", "risk_level": "R1", "expected_return": 2.5, "product_type": "货币基金", "term_days": 0},
    {"product_code": "F100002", "product_name": "天添利货币B", "risk_level": "R1", "expected_return": 2.8, "product_type": "货币基金", "term_days": 0},
    {"product_code": "F200001", "product_name": "XX稳健增利债券A", "risk_level": "R2", "expected_return": 4.5, "product_type": "债券基金", "term_days": 180},
    {"product_code": "F200002", "product_name": "XX纯债优选", "risk_level": "R2", "expected_return": 4.0, "product_type": "债券基金", "term_days": 90},
    {"product_code": "F300001", "product_name": "XX平衡混合基金", "risk_level": "R3", "expected_return": 6.5, "product_type": "混合基金", "term_days": 365},
    {"product_code": "F300002", "product_name": "XX灵活配置混合", "risk_level": "R3", "expected_return": 7.0, "product_type": "混合基金", "term_days": 365},
    {"product_code": "F400001", "product_name": "XX价值成长股票", "risk_level": "R4", "expected_return": 10.0, "product_type": "股票基金", "term_days": 365},
    {"product_code": "F400002", "product_name": "XX行业精选ETF", "risk_level": "R4", "expected_return": 12.0, "product_type": "股票基金", "term_days": 365},
    {"product_code": "F500001", "product_name": "XX量化对冲私募", "risk_level": "R5", "expected_return": 15.0, "product_type": "私募产品", "term_days": 730},
]


class AdvisorService:
    """投顾推荐服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.profile_service = ProfileService(db)

    async def recommend_products(
        self, customer_id: int, top_n: int = 3, risk_level: Optional[str] = None
    ) -> dict:
        """产品推荐"""
        # 获取画像
        profile = await self.profile_service.get_profile(customer_id)
        if not profile:
            return {"recommendations": [], "customer_profile": None, "reasoning": "客户画像不存在，请先创建画像"}

        customer_risk = risk_level or profile.risk_level or "C2"
        allowed_levels = SUITABILITY_MATRIX.get(customer_risk, ["R1", "R2"])

        # 筛选
        candidates = [p for p in MOCK_PRODUCTS if p["risk_level"] in allowed_levels]

        # 打分排序
        for p in candidates:
            risk_match = 1.0 if p["risk_level"] in allowed_levels[:2] else 0.6
            pref_match = 0.7  # 简化
            diversity = 0.8
            return_term = p["expected_return"] / 15.0  # 归一化

            p["match_score"] = (
                RECOMMENDATION_WEIGHTS["risk_match"] * risk_match
                + RECOMMENDATION_WEIGHTS["preference"] * pref_match
                + RECOMMENDATION_WEIGHTS["diversification"] * diversity
                + RECOMMENDATION_WEIGHTS["return_term"] * return_term
            )

        candidates.sort(key=lambda x: x["match_score"], reverse=True)
        top = candidates[:top_n]

        recommendations = [
            ProductRecommend(
                product_code=p["product_code"],
                product_name=p["product_name"],
                risk_level=p["risk_level"],
                expected_return=p["expected_return"],
                match_score=round(p["match_score"], 2),
                reason=self._generate_reason(p, customer_risk),
            )
            for p in top
        ]

        profile_dict = {
            "risk_level": customer_risk,
            "risk_score": profile.risk_score if hasattr(profile, "risk_score") else None,
        }

        return {
            "recommendations": recommendations,
            "customer_profile": profile_dict,
            "reasoning": f"基于客户 {customer_risk} 风险等级，从 {len(candidates)} 个候选产品中推荐 Top{len(top)}",
        }

    async def get_allocation(self, customer_id: int) -> AllocationResult:
        """资产配置建议"""
        profile = await self.profile_service.get_profile(customer_id)
        risk_level = profile.risk_level if profile else "C2"

        template = ASSET_ALLOCATION_TEMPLATES.get(risk_level, ASSET_ALLOCATION_TEMPLATES["C2"])

        explanations = {
            "C1": "保守型配置：以货币基金和债券为主，确保本金安全和稳定收益",
            "C2": "稳健型配置：债券为主，辅以少量混合基金，追求适度增值",
            "C3": "平衡型配置：股债平衡，兼顾收益与风险控制",
            "C4": "进取型配置：股票为主，追求较高收益，承受一定波动",
            "C5": "激进型配置：高比例权益类资产，追求超额收益",
        }

        return AllocationResult(
            customer_id=customer_id,
            risk_level=risk_level,
            allocation={k: round(v * 100, 0) for k, v in template.items()},
            explanation=explanations.get(risk_level, "标准配置"),
        )

    def _generate_reason(self, product: dict, customer_risk: str) -> str:
        risk_map = {"C1": "保守型", "C2": "稳健型", "C3": "平衡型", "C4": "进取型", "C5": "激进型"}
        risk_name = risk_map.get(customer_risk, customer_risk)
        return (
            f"该产品为{product['risk_level']}级{product['product_type']}，"
            f"预期年化{product['expected_return']}%，"
            f"与您的{risk_name}风险偏好匹配"
        )
