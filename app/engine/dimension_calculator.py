"""
四维度打分计算器
基于《投资者风险画像研判规则》(JR-RULE-2024-001)
"""

from typing import Dict, Optional
from app.config.rules_config import (
    AGE_SCORE, EDUCATION_SCORE, OCCUPATION_SCORE, INCOME_SCORE, ASSET_SCORE,
    INVESTMENT_YEARS_SCORE, PRODUCT_COMPLEXITY_SCORE, TRADE_FREQUENCY_SCORE,
    HISTORICAL_RETURN_SCORE, RISK_ASSESSMENT_MAPPING, EMOTIONAL_TRADING_PENALTY,
    LOSS_TOLERANCE_ADJUSTMENT, BEHAVIOR_ABNORMAL_SCORE,
)


# -------- 通用映射辅助 ----------

def _match_range(value: float, table: Dict[str, int]) -> Optional[int]:
    """根据值与范围表的映射规则获取分值"""
    # 直接匹配
    for key, score in table.items():
        if key == str(value) or value == key:
            return score
    return None


def _age_to_score(age: Optional[int]) -> int:
    if age is None:
        return 3  # 默认保守
    if age < 18:
        return 3
    elif age <= 25:
        return AGE_SCORE["18-25"]
    elif age <= 35:
        return AGE_SCORE["26-35"]
    elif age <= 45:
        return AGE_SCORE["36-45"]
    elif age <= 55:
        return AGE_SCORE["46-55"]
    elif age <= 65:
        return AGE_SCORE["56-65"]
    else:
        return AGE_SCORE["65+"]


class BasicDimension:
    """维度一：基础属性特征（满分 25 分）"""

    def calc(self, customer_data: dict) -> dict:
        # 各子项评分
        age_score = _age_to_score(customer_data.get("age"))
        edu_score = EDUCATION_SCORE.get(customer_data.get("education", ""), 4)
        occ_score = OCCUPATION_SCORE.get(customer_data.get("occupation", ""), 5)
        inc_score = INCOME_SCORE.get(customer_data.get("annual_income_range", ""), 3)
        ast_score = ASSET_SCORE.get(customer_data.get("asset_range", ""), 4)

        # 均值归一化
        mean_score = (age_score + edu_score + occ_score + inc_score + ast_score) / 5
        dimension_score = round(mean_score / 10 * 25, 2)

        return {
            "score": dimension_score,
            "detail": {
                "age": age_score,
                "education": edu_score,
                "occupation": occ_score,
                "income": inc_score,
                "assets": ast_score,
            },
        }


class ExperienceDimension:
    """维度二：投资经验特征（满分 25 分）"""

    def calc(self, customer_data: dict) -> dict:
        years_score = INVESTMENT_YEARS_SCORE.get(customer_data.get("investment_years", ""), 2)
        complexity_score = PRODUCT_COMPLEXITY_SCORE.get(customer_data.get("max_product_type", ""), 2)
        freq_score = TRADE_FREQUENCY_SCORE.get(customer_data.get("trade_frequency", ""), 5)
        return_score = HISTORICAL_RETURN_SCORE.get(customer_data.get("historical_return", ""), 3)

        mean_score = (years_score + complexity_score + freq_score + return_score) / 4
        dimension_score = round(mean_score / 10 * 25, 2)

        return {
            "score": dimension_score,
            "detail": {
                "years": years_score,
                "complexity": complexity_score,
                "frequency": freq_score,
                "returns": return_score,
            },
        }


class RiskPreferenceDimension:
    """维度三：风险偏好特征（满分 30 分，下限 0 分）"""

    def calc(self, customer_data: dict) -> dict:
        # 风评映射
        risk_level = customer_data.get("risk_assessment_level", "C2")
        assessment_score = RISK_ASSESSMENT_MAPPING.get(risk_level, 10)

        # 情绪化扣分
        emotional_penalties = sum(
            p["penalty"] for p in EMOTIONAL_TRADING_PENALTY
            if customer_data.get(f"emotional_{p['behavior']}", False)
        )

        # 亏损承受
        loss_tolerance = customer_data.get("loss_tolerance", "10%-20%")
        loss_adj = LOSS_TOLERANCE_ADJUSTMENT.get(loss_tolerance, 0)

        dimension_score = max(0, min(30, assessment_score + emotional_penalties + loss_adj))

        return {
            "score": dimension_score,
            "detail": {
                "assessment": assessment_score,
                "emotional_deduction": emotional_penalties,
                "loss_tolerance": loss_adj,
            },
        }


class BehaviorDimension:
    """维度四：行为异常特征（满分 20 分）"""

    def calc(self, customer_data: dict) -> dict:
        abnormal_behaviors = customer_data.get("abnormal_behaviors", [])

        if not abnormal_behaviors:
            score = BEHAVIOR_ABNORMAL_SCORE["无异常"]
            risk_level_desc = "无异常"
        else:
            low_count = sum(1 for b in abnormal_behaviors if b.get("risk") == "低")
            mid_count = sum(1 for b in abnormal_behaviors if b.get("risk") == "中")
            high_count = sum(1 for b in abnormal_behaviors if b.get("risk") == "高")

            if high_count > 0:
                score = BEHAVIOR_ABNORMAL_SCORE["任何高风险"]
                risk_level_desc = "任何高风险"
            elif mid_count >= 3:
                score = BEHAVIOR_ABNORMAL_SCORE["3项以上中风险"]
                risk_level_desc = "3项以上中风险"
            elif mid_count >= 1:
                score = BEHAVIOR_ABNORMAL_SCORE["1-2项中风险"]
                risk_level_desc = "1-2项中风险"
            elif low_count >= 1:
                score = BEHAVIOR_ABNORMAL_SCORE["1-2项低风险"]
                risk_level_desc = "1-2项低风险"
            else:
                score = BEHAVIOR_ABNORMAL_SCORE["无异常"]
                risk_level_desc = "无异常"

        return {
            "score": score,
            "detail": {
                "abnormal_count": len(abnormal_behaviors),
                "risk_level": risk_level_desc,
            },
        }


class DimensionCalculator:
    """统一四维度计算器"""

    def __init__(self):
        self.basic = BasicDimension()
        self.experience = ExperienceDimension()
        self.risk_pref = RiskPreferenceDimension()
        self.behavior = BehaviorDimension()

    def calc_all(self, customer_data: dict) -> dict:
        return {
            "basic": self.basic.calc(customer_data),
            "experience": self.experience.calc(customer_data),
            "risk_pref": self.risk_pref.calc(customer_data),
            "behavior": self.behavior.calc(customer_data),
        }
