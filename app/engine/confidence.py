"""
置信度计算引擎
标签置信分计算 + 批量计算 + 来源优先级比较
"""

from typing import Optional, List
from datetime import datetime
from app.config.rules_config import CONFIDENCE_SOURCE_INITIAL
from app.config.settings import get_settings

settings = get_settings()


class ConfidenceCalculator:
    """置信度计算器"""

    SOURCE_INITIAL = CONFIDENCE_SOURCE_INITIAL

    def calc_single(
        self,
        source: str,
        evidence_count: int = 0,
        conflict_count: int = 0,
        created_at: Optional[datetime] = None,
    ) -> float:
        """计算单个标签的置信分"""
        base = self.SOURCE_INITIAL.get(source, 0.2)

        # 证据累积增益（每次 +0.05，上限 +0.3）
        gain = min(evidence_count * settings.profile.confidence_evidence_gain, settings.profile.confidence_gain_max)

        # 冲突惩罚（每次 -0.1）
        penalty = conflict_count * settings.profile.confidence_conflict_penalty

        # 时间衰减（每年衰减配置比例）
        age_days = 0
        if created_at:
            age_days = (datetime.now() - created_at).days
        decay = max(0, 1 - age_days / 365 * settings.profile.confidence_decay_rate)

        score = (base + gain - penalty) * decay
        return round(max(0.0, min(1.0, score)), 4)

    def batch_calc(self, tags: list) -> List[float]:
        """批量计算标签置信分"""
        scores = []
        for tag in tags:
            score = self.calc_single(
                source=tag.get("source", "default"),
                evidence_count=tag.get("evidence_count", 0),
                conflict_count=tag.get("conflict_count", 0),
                created_at=tag.get("created_at"),
            )
            scores.append(score)
        return scores

    def compare_source_priority(self, source_a: str, source_b: str) -> int:
        """
        比较两个来源的优先级
        Returns: 1 表示 source_a 更高，-1 表示 source_b 更高，0 表示相同
        """
        priority_order = ["questionnaire", "ai_extract", "self_report", "default"]
        idx_a = priority_order.index(source_a) if source_a in priority_order else 99
        idx_b = priority_order.index(source_b) if source_b in priority_order else 99

        if idx_a < idx_b:
            return 1
        elif idx_a > idx_b:
            return -1
        return 0

    def resolve_conflict(
        self, new_tag: dict, old_tag: dict
    ) -> tuple[dict, Optional[dict]]:
        """
        解决标签冲突
        Returns: (winning_tag, conflict_record_or_none)
        """
        source_new = new_tag.get("source", "default")
        source_old = old_tag.get("source", "default")
        priority = self.compare_source_priority(source_new, source_old)

        if priority > 0:
            # 新标签置信度更高，覆盖
            conflict_record = {
                "old_tag": old_tag,
                "new_tag": new_tag,
                "reason": f"来源 {source_new} 优先级高于 {source_old}",
                "resolved_at": datetime.now().isoformat(),
            }
            return new_tag, conflict_record

        elif priority < 0:
            # 旧标签置信度更高，保留
            conflict_record = {
                "old_tag": old_tag,
                "new_tag": new_tag,
                "reason": f"来源 {source_old} 优先级高于 {source_new}，保留旧值",
                "resolved_at": datetime.now().isoformat(),
            }
            return old_tag, conflict_record

        else:
            # 相同来源，新覆盖旧
            return new_tag, None
