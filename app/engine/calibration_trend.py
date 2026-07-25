"""
校准趋势分析器 —— 连续偏差 → 自动调整风险等级
==============================================

读取客户最近 N 条双轨校准记录，若满足：
  1. 方向一致（全部 over_optimistic 或全部 over_conservative）
  2. 累计触发规则数 ≥ 阈值
  3. 冷却期已过（上次自动调整距今 > cooldown_days）

则自动调整 fin_customer_profile.risk_level，并写入审计记录到 risk_score_record。

设计原则：
  - 保守：每次最多调一档，不跳级
  - 可审计：每条自动调整都有完整的"原因记录 ID 列表"追溯
  - 防震荡：冷却期 + 方向一致性双重保护
"""

import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, List

from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.entities import FinCalibrationRecord, FinCustomerProfile, RiskScoreRecord

logger = logging.getLogger(__name__)


# ── 风险等级单向序列 ──────────────────────────────
_LEVEL_DOWNGRADE = {"C5": "C4", "C4": "C3", "C3": "C2", "C2": "C1", "C1": "C1"}
_LEVEL_UPGRADE   = {"C1": "C2", "C2": "C3", "C3": "C4", "C4": "C5", "C5": "C5"}


@dataclass
class TrendAnalysisResult:
    """趋势分析结果"""
    adjusted: bool = False
    direction: str = "aligned"                     # 本次分析到的方向
    old_level: str = ""
    new_level: str = ""
    reason: str = ""
    referenced_records: List[int] = field(default_factory=list)  # 引用的校准记录 ID
    total_triggers: int = 0                        # 累计触发规则数
    cooldown_blocked: bool = False


class CalibrationTrendAnalyzer:
    """校准趋势分析器 —— 连续偏差累积 → 自动调级"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── 可配置参数（从 rules_config 读取，支持运行时覆盖）─────────────────

    @staticmethod
    def _config() -> dict:
        from app.config.rules_config import CALIBRATION_TREND
        return CALIBRATION_TREND

    # ── 主入口 ──────────────────────────────────────────────────────────

    async def analyze(self, customer_id: int) -> TrendAnalysisResult:
        """
        查询最近 N 条校准记录，判断是否需要自动调整风险等级。

        Returns:
            TrendAnalysisResult — adjusted=True 表示已执行调整
        """
        cfg = self._config()
        if not cfg.get("enabled", True):
            return TrendAnalysisResult()

        lookback = cfg.get("lookback_count", 5)
        threshold = cfg.get("trigger_threshold", 3)
        cooldown_days = cfg.get("cooldown_days", 7)

        # 1. 查询最近 N 条校准记录
        records = await self._query_recent_records(customer_id, lookback)
        if len(records) < 2:  # 至少需要 2 条记录才能判断"趋势"
            return TrendAnalysisResult()

        # 2. 检查方向一致性
        direction = self._check_consistency(records)
        if direction == "aligned":
            return TrendAnalysisResult(direction="aligned", reason="最近校准记录方向不一致，跳过自动调整")

        # 3. 累计触发规则数
        total_triggers = sum(len(r.get("triggered_rules", [])) for r in records)
        if total_triggers < threshold:
            return TrendAnalysisResult(
                direction=direction,
                total_triggers=total_triggers,
                reason=f"累计触发规则数 {total_triggers} < 阈值 {threshold}，跳过自动调整",
            )

        # 4. 冷却期检查
        in_cooldown, last_adjust_at = await self._check_cooldown(customer_id, cooldown_days)
        if in_cooldown:
            return TrendAnalysisResult(
                direction=direction,
                total_triggers=total_triggers,
                cooldown_blocked=True,
                reason=f"冷却期内（上次调整: {last_adjust_at}），跳过自动调整",
            )

        # 5. 读取当前画像等级
        current_level = await self._get_current_level(customer_id)
        if not current_level:
            return TrendAnalysisResult(reason="未找到客户画像记录")

        # 6. 计算新等级
        if direction == "over_optimistic":
            new_level = _LEVEL_DOWNGRADE.get(current_level, current_level)
        else:
            new_level = _LEVEL_UPGRADE.get(current_level, current_level)

        if new_level == current_level:
            return TrendAnalysisResult(
                direction=direction,
                old_level=current_level,
                new_level=current_level,
                reason=f"已在边界等级 {current_level}，无需继续调整",
            )

        # 7. 执行调整
        referenced_ids = [r["id"] for r in records]
        await self._apply_adjustment(customer_id, current_level, new_level, direction,
                                     referenced_ids, total_triggers)

        return TrendAnalysisResult(
            adjusted=True,
            direction=direction,
            old_level=current_level,
            new_level=new_level,
            referenced_records=referenced_ids,
            total_triggers=total_triggers,
            reason=(
                f"连续 {len(records)} 次校准方向一致({direction})，"
                f"累计触发 {total_triggers} 条规则（阈值≥{threshold}），"
                f"自动调整: {current_level} → {new_level}"
            ),
        )

    # ── 内部查询方法 ───────────────────────────────────────────────────

    async def _query_recent_records(self, customer_id: int, limit: int) -> List[dict]:
        """查询客户最近 N 条非 aligned 校准记录（按时间倒序）"""
        stmt = (
            select(FinCalibrationRecord)
            .where(
                FinCalibrationRecord.customer_id == customer_id,
                FinCalibrationRecord.direction != "aligned",
            )
            .order_by(FinCalibrationRecord.calibrate_time.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        rows = result.scalars().all()

        records = []
        for r in rows:
            triggered = r.triggered_rules or []
            # 兼容两种存储格式：list[dict] / list[RuleEvidence]
            if isinstance(triggered, list):
                normalized = []
                for t in triggered:
                    if hasattr(t, 'rule_id'):
                        normalized.append({"rule_id": t.rule_id, "rule_name": t.rule_name,
                                           "direction": t.direction, "detail": t.detail})
                    elif isinstance(t, dict):
                        normalized.append(t)
                triggered = normalized
            records.append({
                "id": r.id,
                "direction": r.direction,
                "calibrate_time": r.calibrate_time,
                "triggered_rules": triggered,
            })
        return records

    @staticmethod
    def _check_consistency(records: List[dict]) -> str:
        """检查所有记录方向是否一致。返回方向字符串或 'aligned'"""
        directions = {r["direction"] for r in records}
        if len(directions) == 1:
            return list(directions)[0]
        return "aligned"

    async def _check_cooldown(self, customer_id: int, cooldown_days: int) -> tuple:
        """检查是否在冷却期内。返回 (bool, last_adjust_at_str)"""
        cutoff = datetime.now() - timedelta(days=cooldown_days)
        stmt = (
            select(RiskScoreRecord)
            .where(
                RiskScoreRecord.customer_id == customer_id,
                RiskScoreRecord.trigger_type == "auto_calibration",
                RiskScoreRecord.create_time >= cutoff,
            )
            .order_by(RiskScoreRecord.create_time.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        last = result.scalar_one_or_none()
        if last:
            return True, last.create_time.isoformat() if last.create_time else "unknown"
        return False, None

    async def _get_current_level(self, customer_id: int) -> Optional[str]:
        stmt = select(FinCustomerProfile).where(FinCustomerProfile.customer_id == customer_id)
        result = await self.db.execute(stmt)
        profile = result.scalar_one_or_none()
        if profile:
            return profile.risk_level
        return None

    # ── 执行调整 ───────────────────────────────────────────────────────

    async def _apply_adjustment(
        self, customer_id: int, old_level: str, new_level: str,
        direction: str, referenced_ids: List[int], total_triggers: int,
    ):
        """更新画像等级 + 写入审计记录"""
        now = datetime.now()

        # 1. 更新 fin_customer_profile
        stmt = select(FinCustomerProfile).where(FinCustomerProfile.customer_id == customer_id)
        result = await self.db.execute(stmt)
        profile = result.scalar_one_or_none()
        if profile:
            profile.risk_level = new_level
            profile.update_time = now

        # 2. 写入审计记录到 risk_score_record
        audit = RiskScoreRecord(
            customer_id=customer_id,
            rating_date=now,
            risk_level=new_level,
            trigger_type="auto_calibration",
            detail_json={
                "action": "auto_adjust",
                "direction": direction,
                "old_level": old_level,
                "new_level": new_level,
                "referenced_calibration_ids": referenced_ids,
                "total_triggers": total_triggers,
                "lookback_count": self._config().get("lookback_count", 5),
                "threshold": self._config().get("trigger_threshold", 3),
            },
            create_time=now,
        )
        self.db.add(audit)

        await self.db.flush()

        logger.info(
            "校准趋势自动调整: customer=%s %s→%s direction=%s triggers=%d records=%s",
            customer_id, old_level, new_level, direction, total_triggers, referenced_ids,
        )
