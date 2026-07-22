"""
综合置信度重排工具（FinalConfidenceRankTool）
============================================
基于场景权重对预警记忆进行综合排序。
需求文档 F4.3 + 记忆架构设计 §4
"""

from app.engine.confidence import ConfidenceCalculator


class FinalConfidenceRankTool:
    """综合置信度重排 — 风险研判场景"""

    SCENARIO_WEIGHTS: dict[str, dict[str, float]] = {
        "产品推荐": {"semantic": 0.30, "timeliness": 0.20, "accuracy": 0.25, "base": 0.15, "conflict": 0.10},
        "风险研判": {"semantic": 0.15, "timeliness": 0.30, "accuracy": 0.25, "base": 0.20, "conflict": 0.10},
        "客户画像": {"semantic": 0.20, "timeliness": 0.25, "accuracy": 0.20, "base": 0.25, "conflict": 0.10},
        "知识检索": {"semantic": 0.35, "timeliness": 0.15, "accuracy": 0.20, "base": 0.20, "conflict": 0.10},
    }

    def __init__(self):
        self.conf_calc = ConfidenceCalculator()

    def rank(self, memory_units: list[dict], scenario: str = "风险研判") -> list[dict]:
        """
        综合重排记忆单元，返回按 final_score 降序的列表。

        Args:
            memory_units: 记忆单元列表
            scenario: 场景名称，默认"风险研判"

        Returns:
            排序后的列表，每项新增 final_score 字段
        """
        weights = self.SCENARIO_WEIGHTS.get(scenario, self.SCENARIO_WEIGHTS["知识检索"])

        for unit in memory_units:
            semantic = unit.get("semantic_similarity", 0.5)
            timeliness = self._calc_timeliness(unit.get("age_days", 0))
            accuracy = unit.get("historical_accuracy", 0.5)
            base_conf = unit.get("confidence_score", 0.5)
            conflict = unit.get("conflict_count", 0) * 0.1

            final = (
                weights["semantic"] * semantic
                + weights["timeliness"] * timeliness
                + weights["accuracy"] * accuracy
                + weights["base"] * base_conf
                - weights["conflict"] * conflict
            )
            unit["final_score"] = round(max(0.0, min(1.0, final)), 4)

        return sorted(memory_units, key=lambda x: x.get("final_score", 0), reverse=True)

    @staticmethod
    def _calc_timeliness(age_days: int) -> float:
        """时效性计算：指数衰减，半年半衰期"""
        import math
        return round(math.exp(-age_days / 180), 4)
