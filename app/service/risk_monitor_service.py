"""
风控监测服务
============
接收交易事件 → 规则匹配 → 预警分级 → MySQL持久化 + 工单 + Redis双写
"""

import logging
from datetime import datetime
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tool.risk_monitor_rules import BaseAMLRule, ALL_AML_RULES
from app.model.entities import FinRiskAlert, BizWorkOrder
from app.tool.memory_validator import MemoryUnitValidator

logger = logging.getLogger(__name__)


class RiskMonitorService:
    """风控监测引擎"""

    def __init__(self):
        self.rules = ALL_AML_RULES
        self.validator = MemoryUnitValidator()

    def evaluate_all(self, tx: dict) -> list[BaseAMLRule]:
        """逐条匹配所有规则，返回触发的规则列表（纯CPU计算）"""
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
            bool(triggered_ids & _extract_rule_ids(a.get("trigger_rules", [])))
            for a in history
        )
        adjusted = count + (1 if is_repeat else 0)
        if adjusted == 1 and not is_repeat:
            return "low"
        elif adjusted <= 3:
            return "medium"
        return "high"

    def build_alert(self, tx: dict, triggered: list[BaseAMLRule], level: str, confidence: float) -> dict:
        """组装预警对象"""
        rule_list = [{"rule_id": r.rule_id, "rule_name": r.rule_name, "risk_level": r.risk_level} for r in triggered]
        names = "、".join(r.rule_name for r in triggered)
        rec = {"low": "记录并持续关注", "medium": "1个工作日内核实", "high": "立即核实，必要时冻结上报"}
        return {
            "customer_id": tx["customer_id"],
            "transaction_id": tx.get("transaction_id", ""),
            "alert_level": level,
            "trigger_rules": rule_list,
            "confidence": round(confidence, 2),
            "summary": f"客户{tx['customer_id']}触发{len(triggered)}条规则：{names}",
            "recommendation": rec.get(level, ""),
            "status": "pending",
        }

    async def save_alert(self, db: AsyncSession, alert: dict) -> int:
        """保存预警到 MySQL + 黄色/红色自动创建工单 + Redis双写"""
        # 取第一条触发规则的编号作为 alert_type（对齐功能设计 §4.3）
        first_rule = alert["trigger_rules"][0]["rule_id"] if alert["trigger_rules"] else "unknown"
        entity = FinRiskAlert(
            customer_id=alert["customer_id"],
            alert_type=first_rule,
            alert_level=alert["alert_level"],
            trigger_detail=alert["summary"],
            transaction_ids={"tx_id": alert.get("transaction_id", ""), "trigger_rules": alert["trigger_rules"]},
            status="未处理",
            create_time=datetime.now(),
        )
        db.add(entity)
        await db.flush()
        await db.refresh(entity)
        logger.info(f"预警已写入MySQL: id={entity.id}")

        # 黄色/红色预警 → 自动创建工单
        if alert["alert_level"] in ("medium", "high"):
            await self._create_work_order(db, alert, entity.id)

        # Redis 双写
        await self._add_pending_alert(entity.id)

        # 发布风控预警事件 → 通知投顾/客服 Agent 更新客户风险标记（阶段3协作闭环）
        if alert["alert_level"] in ("medium", "high"):
            try:
                from app.service.event_bus import publish_event, EVENT_RISK_ALERT
                await publish_event(EVENT_RISK_ALERT, {
                    "alert_id": entity.id,
                    "customer_id": alert["customer_id"],
                    "alert_level": alert["alert_level"],
                    "trigger_rules": alert["trigger_rules"],
                    "confidence": alert["confidence"],
                    "summary": alert["summary"],
                })
                logger.info(f"风控预警事件已广播: 客户{alert['customer_id']} {alert['alert_level']}级")
            except Exception as e:
                logger.warning(f"事件广播失败(不影响主流程): {e}")

        return entity.id

    async def _create_work_order(self, db: AsyncSession, alert: dict, alert_id: int):
        """自动创建可疑交易工单"""
        now = datetime.now()
        wo = BizWorkOrder(
            work_order_no=f"WO{now.strftime('%Y%m%d%H%M%S')}{alert_id}",
            order_type="可疑交易上报",
            sub_type=alert["alert_level"],
            customer_id=alert["customer_id"],
            submitter_id=0,
            priority="紧急" if alert["alert_level"] == "high" else "普通",
            status="处理中",
            biz_content={"alert_id": alert_id, "trigger_rules": alert["trigger_rules"],
                         "summary": alert["summary"], "recommendation": alert["recommendation"]},
            remark=f"风控Agent自动创建 - {alert['alert_level']}级预警",
            create_time=now,
        )
        db.add(wo)
        await db.flush()
        logger.info(f"工单已创建: {wo.work_order_no}")

    async def _add_pending_alert(self, alert_id: int):
        """Redis 双写: risk:alert:pending"""
        try:
            from app.config.database import get_redis
            r = await get_redis()
            await r.sadd("risk:alert:pending", str(alert_id))
        except Exception as e:
            logger.warning(f"Redis双写失败(不影响主流程): {e}")

    async def get_alerts(self, db: AsyncSession, customer_id: int = None,
                         level: str = None, status: str = None,
                         days: int = 30, page: int = 1, pagesize: int = 20) -> tuple[int, list[dict]]:
        """查询历史预警（从 MySQL）"""
        stmt = select(FinRiskAlert).order_by(FinRiskAlert.create_time.desc())
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
        return total, [_to_dict(a) for a in all_alerts[start:start + pagesize]]

    async def get_alert(self, db: AsyncSession, alert_id: str) -> Optional[dict]:
        """查询单条预警（按主键id）"""
        stmt = select(FinRiskAlert).where(FinRiskAlert.id == int(alert_id))
        result = await db.execute(stmt)
        alert = result.scalar_one_or_none()
        return _to_dict(alert) if alert else None

    async def handle_alert(self, db: AsyncSession, alert_id: str, action: str, handler_id: int, note: str) -> Optional[dict]:
        """处理预警"""
        stmt = select(FinRiskAlert).where(FinRiskAlert.id == int(alert_id))
        result = await db.execute(stmt)
        alert = result.scalar_one_or_none()
        if not alert:
            return None
        alert.status = action
        alert.handler_id = handler_id
        alert.handle_result = note
        alert.update_time = datetime.now()
        await db.flush()
        return _to_dict(alert)


def _extract_rule_ids(trigger_rules) -> set:
    """从trigger_rules中提取规则ID集合，兼容[dict]和[str]两种格式"""
    ids = set()
    for item in trigger_rules:
        if isinstance(item, dict):
            ids.add(item.get("rule_id", ""))
        else:
            ids.add(str(item))
    return ids


def _to_dict(a: FinRiskAlert) -> dict:
    """实体转字典"""
    tx_ids = a.transaction_ids or {}
    return {
        "alert_id": str(a.id),
        "customer_id": a.customer_id,
        "alert_level": a.alert_level,
        "trigger_rules": tx_ids.get("trigger_rules", []),
        "summary": a.trigger_detail,
        "status": a.status,
        "created_at": a.create_time.isoformat() if a.create_time else "",
    }
