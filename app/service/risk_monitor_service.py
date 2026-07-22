"""
风控监测服务
============
接收交易事件 → 规则匹配 → 预警分级 → 生成预警
"""

import logging
from datetime import datetime
from typing import Optional

from app.tool.risk_monitor_rules import BaseAMLRule, ALL_AML_RULES

logger = logging.getLogger(__name__)

# 内存存储（后续接 MySQL）
_alert_store: dict = {}


class RiskMonitorService:
    """风控监测引擎"""

    def __init__(self):
        self.rules = ALL_AML_RULES

    def evaluate_all(self, tx: dict) -> list[BaseAMLRule]:
        """逐条匹配所有规则，返回触发的规则列表"""
        triggered = []
        for rule in self.rules:
            try:
                if rule.evaluate(tx):
                    triggered.append(rule)
            except Exception as e:
                logger.warning(f"规则 {rule.rule_id} 评估异常: {e}")
        return triggered

    def grade(self, triggered: list[BaseAMLRule], history: list[dict], tx: dict) -> str:
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
        alert_id = f"ALT{now.strftime('%Y%m%d%H%M%S')}"
        rule_list = [{"rule_id": r.rule_id, "rule_name": r.rule_name, "risk_level": r.risk_level} for r in triggered]
        names = "、".join(r.rule_name for r in triggered)
        rec = {"low": "记录并持续关注", "medium": "1个工作日内核实", "high": "立即核实，必要时冻结上报"}

        return {
            "alert_id": alert_id,
            "customer_id": tx["customer_id"],
            "alert_level": level,
            "trigger_rules": rule_list,
            "confidence": round(confidence, 2),
            "summary": f"客户{tx['customer_id']}触发{len(triggered)}条规则：{names}",
            "recommendation": rec.get(level, ""),
            "status": "pending",
            "created_at": now.isoformat(),
        }

    def save_alert(self, alert: dict):
        """保存预警（当前内存版，后续写入 MySQL + Redis）"""
        _alert_store[alert["alert_id"]] = alert

    def get_alerts(self, customer_id: int = None, level: str = None, status: str = None,
                   days: int = 30, page: int = 1, pagesize: int = 20) -> tuple:
        """查询历史预警"""
        alerts = list(_alert_store.values())
        if customer_id:
            alerts = [a for a in alerts if a["customer_id"] == customer_id]
        if level:
            alerts = [a for a in alerts if a["alert_level"] == level]
        if status:
            alerts = [a for a in alerts if a["status"] == status]
        total = len(alerts)
        start = (page - 1) * pagesize
        return total, alerts[start:start + pagesize]

    def get_alert(self, alert_id: str) -> Optional[dict]:
        return _alert_store.get(alert_id)

    def handle_alert(self, alert_id: str, action: str):
        alert = _alert_store.get(alert_id)
        if alert:
            alert["status"] = action
        return alert
