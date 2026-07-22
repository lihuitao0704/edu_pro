"""综合置信度重排工具（FinalConfidenceRankTool）"""
from app.engine.confidence import ConfidenceCalculator


class FinalConfidenceRankTool:
    SCENARIO_WEIGHTS = {
        "产品推荐": {"semantic": 0.30, "timeliness": 0.20, "accuracy": 0.25, "base": 0.15, "conflict": 0.10},
        "风险研判": {"semantic": 0.15, "timeliness": 0.30, "accuracy": 0.25, "base": 0.20, "conflict": 0.10},
        "客户画像": {"semantic": 0.20, "timeliness": 0.25, "accuracy": 0.20, "base": 0.25, "conflict": 0.10},
        "知识检索": {"semantic": 0.35, "timeliness": 0.15, "accuracy": 0.20, "base": 0.20, "conflict": 0.10},
    }

    def rank(self, memory_units: list, scenario: str = "风险研判") -> list:
        weights = self.SCENARIO_WEIGHTS.get(scenario, self.SCENARIO_WEIGHTS["知识检索"])
        for unit in memory_units:
            final = (weights["semantic"] * unit.get("semantic_similarity", 0.5)
                     + weights["timeliness"] * self._calc_timeliness(unit.get("age_days", 0))
                     + weights["accuracy"] * unit.get("historical_accuracy", 0.5)
                     + weights["base"] * unit.get("confidence_score", 0.5)
                     - weights["conflict"] * unit.get("conflict_count", 0) * 0.1)
            unit["final_score"] = round(max(0.0, min(1.0, final)), 4)
        return sorted(memory_units, key=lambda x: x.get("final_score", 0), reverse=True)

    @staticmethod
    def _calc_timeliness(age_days: int) -> float:
        import math
        return round(math.exp(-age_days / 180), 4)
