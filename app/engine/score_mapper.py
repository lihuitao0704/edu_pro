"""分数 → 风险等级映射"""

from typing import List
from app.config.rules_config import (
    RISK_LEVEL_MAPPING,
    SUITABILITY_MATRIX,
    DIMENSION_WEIGHTS,
)


def map_score_to_risk_level(total_score: float) -> tuple[str, str]:
    """
    综合分映射到 C1-C5 等级
    Returns: (level_code, level_name)
    """
    for min_s, max_s, code, name in RISK_LEVEL_MAPPING:
        if min_s <= total_score <= max_s:
            return code, name
    # 兜底
    if total_score > 100:
        return "C5", "激进型"
    return "C1", "保守型"


def get_suitable_products(risk_level: str) -> List[str]:
    """获取某等级可购买的产品等级列表"""
    return SUITABILITY_MATRIX.get(risk_level, ["R1"])


def check_suitability(customer_level: str, product_level: str) -> bool:
    """检查客户是否能购买某等级产品"""
    allowed = SUITABILITY_MATRIX.get(customer_level, [])
    return product_level in allowed


def calc_total_score(dimension_scores: dict) -> float:
    """
    计算综合得分（100分制）
    各维度得分已含权重（维度一满分25 + 维度二满分25 + 维度三满分30 + 维度四满分20 = 100）
    dimension_scores: {"basic": 17.5, "experience": 16.25, "risk_pref": 15.0, "behavior": 15.0}
    """
    total = sum(dimension_scores.get(dim, 0) for dim in ["basic", "experience", "risk_pref", "behavior"])
    return round(total, 2)
