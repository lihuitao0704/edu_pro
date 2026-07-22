"""
特殊场景处理器
信息不完整、自评vs AI冲突、特殊人群、多账户合并
"""

from typing import Optional, List
from app.config.rules_config import (
    SPECIAL_POPULATION_RULES, SELF_VS_AI_CONFLICT, INCOMPLETE_INFO_RULES,
)


class SpecialCaseResult:
    def __init__(self):
        self.adjustments: List[str] = []
        self.downgrade_levels: int = 0  # 评级下调档数
        self.product_restrictions: List[str] = []
        self.requires_manual_review: bool = False
        self.customer_level_overrides: Optional[str] = None


class SpecialCaseHandler:
    """特殊场景处理器"""

    def handle(self, customer_data: dict, ai_level: str) -> SpecialCaseResult:
        result = SpecialCaseResult()

        self._handle_incomplete_info(customer_data, result)
        self._handle_self_assessment_conflict(customer_data, ai_level, result)
        self._handle_special_population(customer_data, result)

        return result

    def _handle_incomplete_info(self, data: dict, result: SpecialCaseResult):
        """处理信息不完整"""
        missing_count = 0

        # 收入缺失
        if not data.get("annual_income_range"):
            result.adjustments.append(INCOMPLETE_INFO_RULES["收入缺失"])
            result.downgrade_levels += 1
            missing_count += 1

        # 投资经验缺失
        if not data.get("investment_years"):
            result.adjustments.append(INCOMPLETE_INFO_RULES["投资经验缺失"])
            missing_count += 1

        # 资产缺失
        if not data.get("total_assets"):
            result.adjustments.append(INCOMPLETE_INFO_RULES["资产缺失"])
            missing_count += 1

        # 联系方式失效
        if not data.get("phone") and not data.get("email"):
            result.adjustments.append(INCOMPLETE_INFO_RULES["联系方式失效"])
            missing_count += 1

        # 多项缺失
        if missing_count > 3:
            result.adjustments.append(INCOMPLETE_INFO_RULES["多项缺失(>3项)"])
            result.requires_manual_review = True

    def _handle_self_assessment_conflict(self, data: dict, ai_level: str, result: SpecialCaseResult):
        """处理客户自评与 AI 评估不一致"""
        self_level = data.get("self_assessment_level")
        if self_level is None:
            return

        level_map = {"C1": 1, "C2": 2, "C3": 3, "C4": 4, "C5": 5}
        self_idx = level_map.get(self_level, 2)
        ai_idx = level_map.get(ai_level, 2)
        diff = abs(self_idx - ai_idx)

        if diff >= 3:
            result.adjustments.append(SELF_VS_AI_CONFLICT["diff_3+"])
            result.requires_manual_review = True
        elif diff >= 2:
            result.adjustments.append(SELF_VS_AI_CONFLICT["diff_2"])
            result.requires_manual_review = True
        elif diff >= 1:
            result.adjustments.append(SELF_VS_AI_CONFLICT["diff_1"])

    def _handle_special_population(self, data: dict, result: SpecialCaseResult):
        """处理特殊人群"""
        occupation = data.get("occupation", "")

        # 在校学生
        if occupation == "在校学生" or data.get("is_student", False):
            rule = SPECIAL_POPULATION_RULES["在校学生"]
            result.adjustments.append(rule["note"])
            result.product_restrictions = rule["product_limit"]
            result.downgrade_levels += 1

        # 失信被执行人
        if data.get("is_dishonest", False):
            result.adjustments.append(SPECIAL_POPULATION_RULES["失信被执行人"]["action"])

        # 外籍人士（简化处理）
        if data.get("is_foreign", False):
            result.adjustments.append(SPECIAL_POPULATION_RULES["外籍人士"]["action"])
            result.downgrade_levels += 1
