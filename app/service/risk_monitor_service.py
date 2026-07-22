"""
风控监测服务
============
接收交易事件 → 规则匹配 → 预警分级 → 生成预警 → MySQL持久化
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tool.risk_monitor_rules import BaseAMLRule, ALL_AML_RULES
from app.model.entities import FinRiskAlert

logger = logging.getLogger(__name__)


class RiskMonitorService:
    """风控监测引擎"""

    def __init__(self):
        self.rules = ALL_AML_RULES

    def evaluate_all(self, tx: dict) -> list[BaseAMLRule]:
        """逐条匹配所有规则，返回触发的规则列表（纯CPU计算，不需async）"""
        triggered = []
        for rule in self.rules:
            try:
                if rule.evaluate(tx):
                    triggered.append(rule)
            except Exception as e:
                logger.warning(f"规则 {rule.rule_id} 评估异常: {e}")
        return triggered

    def grade(self, triggered: list[BaseAMLRule], history: list[dict], tx: dict) -> Optional[str]:
        """预警分级: low/medium/high"""
        count = len(triggered)
        if count == 0:
            return None

        triggered_ids = {r.rule_id for r in triggered}
        is_repeat = any(
            set(a.get("trigger_rules", [])) & triggered_ids for a in history
        )
        adjusted = count + (1 if is_repeat else 0)

        if adjusted == 1 and not is_repeat:
            return "low"
        elif adjusted <= 3:
            return "medium"
        return "high"

    def build_alert(self, tx: dict, triggered: list[BaseAMLRule], level: str, confidence: float) -> dict:
        """组装预警对象"""
        now = datetime.now()
        rule_list = [{"rule_id": r.rule_id, "rule_name": r.rule_name, "risk_level": r.risk_level} for r in triggered]
        names = "、".join(r.rule_name for r in triggered)
        rec = {"low": "记录并持续关注", "medium": "1个工作日内核实", "high": "立即核实，必要时冻结上报"}

        return {
            "alert_id": f"ALT{now.strftime('%Y%m%d%H%M%S')}",
            "customer_id": tx["customer_id"],
            "alert_level": level,
            "trigger_rules": rule_list,
            "confidence": round(confidence, 2),
            "summary": f"客户{tx['customer_id']}触发{len(triggered)}条规则：{names}",
            "recommendation": rec.get(level, ""),
            "status": "pending",
            "created_at": now.isoformat(),
        }

    async def save_alert(self, db: AsyncSession, alert: dict):
        """保存预警到 MySQL"""
        entity = FinRiskAlert(
            alert_id=alert["alert_id"],
            customer_id=alert["customer_id"],
            alert_level=alert["alert_level"],
            trigger_rules=alert["trigger_rules"],
            confidence=Decimal(str(alert["confidence"])),
            trigger_detail=alert["summary"],
            status="pending",
        )
        db.add(entity)
        await db.flush()
        logger.info(f"预警已写入MySQL: {alert['alert_id']}")

    async def get_alerts(self, db: AsyncSession, customer_id: int = None,
                         level: str = None, status: str = None,
                         days: int = 30, page: int = 1, pagesize: int = 20) -> tuple[int, list[dict]]:
        """查询历史预警（从 MySQL）"""
        stmt = select(FinRiskAlert).order_by(FinRiskAlert.created_at.desc())

        if customer_id:
            stmt = stmt.where(FinRiskAlert.customer_id == customer_id)
        if level:
            stmt = stmt.where(FinRiskAlert.alert_level == level)
        if status:
            stmt = stmt.where(FinRiskAlert.status == status)

        result = await db.execute(stmt)
        all_alerts = result.scalars().all()

        total = len(all_alerts)
        start = (page - 1) * pagesize
        page_alerts = all_alerts[start:start + pagesize]

        return total, [_alert_to_dict(a) for a in page_alerts]

    async def get_alert(self, db: AsyncSession, alert_id: str) -> Optional[dict]:
        """查询单条预警"""
        stmt = select(FinRiskAlert).where(FinRiskAlert.alert_id == alert_id)
        result = await db.execute(stmt)
        alert = result.scalar_one_or_none()
        return _alert_to_dict(alert) if alert else None

    async def handle_alert(self, db: AsyncSession, alert_id: str, action: str, handler_id: int, note: str) -> Optional[dict]:
        """处理预警"""
        stmt = select(FinRiskAlert).where(FinRiskAlert.alert_id == alert_id)
        result = await db.execute(stmt)
        alert = result.scalar_one_or_none()
        if not alert:
            return None
        alert.status = action
        alert.handler_id = handler_id
        alert.handle_note = note
        alert.resolved_at = datetime.now()
        await db.flush()
        return _alert_to_dict(alert)


def _alert_to_dict(a: FinRiskAlert) -> dict:
    return {
        "alert_id": a.alert_id,
        "customer_id": a.customer_id,
        "alert_level": a.alert_level,
        "trigger_rules": a.trigger_rules,
        "confidence": float(a.confidence) if a.confidence else 0.0,
        "summary": a.trigger_detail,
        "status": a.status,
        "created_at": a.created_at.isoformat() if a.created_at else "",
    }
