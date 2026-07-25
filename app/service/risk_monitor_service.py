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
        """预警分级: low/medium/high

        先看规则优先级（P1/P2档直接high），再看触发条数。
        """
        count = len(triggered)
        if count == 0:
            return None

        # P1/P2 档规则：制裁国、PEP、涉赌涉诈、资金归集、资金转移模式异常
        # 触发即直接红色预警，不依赖触发条数
        if any(r.weight >= 1.0 for r in triggered):
            return "high"

        triggered_ids = {r.rule_id for r in triggered}
        is_repeat = any(
            bool(triggered_ids & _extract_rule_ids(a.get("trigger_rules", [])))
            for a in history
        )
        # 权重叠加：多条中低危规则累计权重≥2.5 → 升级为high
        total_weight = sum(r.weight for r in triggered)
        if total_weight >= 2.5:
            return "high"

        adjusted = count + (1 if is_repeat else 0)
        if adjusted == 1 and not is_repeat:
            return "low"
        elif adjusted <= 3:
            return "medium"
        return "high"

    def build_alert(self, tx: dict, triggered: list[BaseAMLRule], level: str, confidence: float) -> dict:
        """组装预警对象（含可解释性增强：每条规则带触发条件说明）"""
        rule_list = [{"rule_id": r.rule_id, "rule_name": r.rule_name, "risk_level": r.risk_level,
                      "trigger_condition": r.trigger_condition} for r in triggered]
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
            status="pending",
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

        # 高风险累计告警：同一客户≥2条pending高预警 → 自动生成汇总告警
        if alert["alert_level"] == "high":
            try:
                from sqlalchemy import func, text
                cnt_result = await db.execute(
                    text("SELECT COUNT(*) FROM fin_risk_alert WHERE customer_id=:cid AND alert_level='high' AND status='pending'"),
                    {"cid": alert["customer_id"]},
                )
                pending_high = cnt_result.scalar()
                if pending_high >= 2:
                    # 今天已产生过累计告警则跳过
                    dup_result = await db.execute(
                        text("SELECT id FROM fin_risk_alert WHERE customer_id=:cid AND alert_type='cumulative_high' AND DATE(create_time)=CURDATE()"),
                        {"cid": alert["customer_id"]},
                    )
                    if not dup_result.first():
                        summary = FinRiskAlert(
                            customer_id=alert["customer_id"],
                            alert_type="cumulative_high",
                            alert_level="high",
                            trigger_detail=f"高风险累计告警: 该客户当前有{pending_high}条待处理高预警",
                            transaction_ids={"pending_high_count": pending_high},
                            status="pending",
                            create_time=datetime.now(),
                        )
                        db.add(summary)
                        await db.flush()
                        logger.info(f"累计高风险告警: 客户{alert['customer_id']} 已达{pending_high}条高预警")
            except Exception as e:
                logger.warning(f"累计高风险检查失败(不影响主流程): {e}")

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
        if action not in {"resolved", "false_positive", "processing"}:
            raise ValueError("不支持的预警处理动作")
        stmt = select(FinRiskAlert).where(FinRiskAlert.id == int(alert_id))
        result = await db.execute(stmt)
        alert = result.scalar_one_or_none()
        if not alert:
            return None
        alert.status = action
        alert.handler_id = handler_id
        alert.handle_result = note
        alert.update_time = datetime.now()

        work_order_stmt = (
            select(BizWorkOrder)
            .where(BizWorkOrder.biz_content["alert_id"].as_integer() == int(alert_id))
            .order_by(BizWorkOrder.id.desc())
        )
        work_order_result = await db.execute(work_order_stmt)
        work_order = work_order_result.scalar_one_or_none()
        if work_order:
            if action in {"resolved", "false_positive"}:
                work_order.status = "已完成"
                work_order.current_node = "已关闭"
            else:
                work_order.status = "处理中"
                work_order.current_node = "风险核实"
            work_order.handler_id = handler_id
            work_order.update_time = datetime.now()

        if action in {"resolved", "false_positive"}:
            try:
                from app.config.database import get_redis

                redis = await get_redis()
                await redis.srem("risk:alert:pending", str(alert_id))
            except Exception as exc:
                logger.warning("清理预警待办失败: %s", exc)
        await db.flush()
        return _to_dict(alert)

    async def save_cs_signal_alert(self, db: AsyncSession, payload: dict) -> int:
        """
        处理来自客服渠道的风控信号 → 生成预警记录

        C5 反向联动：客服Agent在对话中检测到可疑信号，通过 event_bus 传递到此方法。
        复用现有风控管线（fin_risk_alert 表），通过 alert_type 前缀 cs_signal:* 区分来源。

        Args:
            db: 数据库会话
            payload: C5 事件 payload，包含:
                - customer_id: 客户ID
                - signal_type: 信号类型 (account_compromise / social_engineering / ...)
                - signal_level: 信号等级 (low / medium / high)
                - session_id: 会话ID
                - evidence: 证据上下文
                - confidence: 置信度

        Returns:
            预警记录 ID，失败返回 0
        """
        customer_id = payload.get("customer_id")
        signal_type = payload.get("signal_type", "unknown")
        signal_level = payload.get("signal_level", "medium")
        session_id = payload.get("session_id", "")
        evidence = payload.get("evidence", {})
        confidence = payload.get("confidence", 0.6)

        if not customer_id:
            logger.warning("C5信号缺少 customer_id，跳过")
            return 0

        # 组装预警对象
        alert_type = f"cs_signal:{signal_type}"
        summary = (
            f"客服渠道信号: 客户{customer_id}在对话中触发{signal_type}信号"
            f"(等级={signal_level}, 置信度={confidence})"
        )
        message_snippet = (evidence.get("message") or "")[:200]
        keywords = evidence.get("keywords_hit", [])

        now = datetime.now()
        entity = FinRiskAlert(
            customer_id=customer_id,
            alert_type=alert_type,
            alert_level=signal_level,
            trigger_detail=summary,
            transaction_ids={
                "source": "customer_agent",
                "session_id": session_id,
                "signal_type": signal_type,
                "keywords": keywords,
                "message": message_snippet,
                "confidence": confidence,
            },
            status="pending",
            create_time=now,
        )
        db.add(entity)
        await db.flush()
        await db.refresh(entity)
        logger.info(
            "C5信号预警已写入MySQL: id=%s | customer=%s | type=%s | level=%s",
            entity.id, customer_id, alert_type, signal_level,
        )

        # 黄色/红色预警 → 自动创建工单
        if signal_level in ("medium", "high"):
            await self._create_cs_signal_work_order(db, payload, entity.id)

        # Redis 双写
        await self._add_pending_alert(entity.id)

        # 更新客户画像 risk_flag（复用现有联动逻辑）
        await self._update_risk_flag_from_cs_signal(customer_id, signal_level)

        return entity.id

    async def _create_cs_signal_work_order(
        self, db: AsyncSession, payload: dict, alert_id: int
    ):
        """C5 信号自动创建可疑对话工单"""
        customer_id = payload.get("customer_id")
        signal_level = payload.get("signal_level", "medium")
        signal_type = payload.get("signal_type", "unknown")
        now = datetime.now()

        wo = BizWorkOrder(
            work_order_no=f"WOC{now.strftime('%Y%m%d%H%M%S')}{alert_id}",
            order_type="可疑对话上报",
            sub_type=signal_level,
            customer_id=customer_id,
            submitter_id=0,
            priority="紧急" if signal_level == "high" else "普通",
            status="处理中",
            biz_content={
                "alert_id": alert_id,
                "signal_type": signal_type,
                "source": "customer_agent",
                "session_id": payload.get("session_id", ""),
                "evidence": payload.get("evidence", {}),
            },
            remark=f"客服Agent C5反向联动自动创建 - {signal_level}级({signal_type})",
            create_time=now,
        )
        db.add(wo)
        await db.flush()
        logger.info("C5工单已创建: %s | customer=%s", wo.work_order_no, customer_id)

    async def _update_risk_flag_from_cs_signal(
        self, customer_id: int, signal_level: str
    ) -> None:
        """C5 信号触发更新客户画像 risk_flag（MySQL + Redis）"""
        risk_flag = "high" if signal_level == "high" else "warning"

        # 1. 更新 MySQL 画像
        try:
            from sqlalchemy import text
            from app.config.database import async_session_factory
            async with async_session_factory() as db:
                await db.execute(
                    text(
                        "UPDATE fin_customer_profile "
                        "SET risk_flag = :flag WHERE customer_id = :cid"
                    ),
                    {"flag": risk_flag, "cid": customer_id},
                )
                await db.commit()
            logger.info(
                "C5联动(MySQL): 客户%s risk_flag 更新为 %s", customer_id, risk_flag
            )
        except Exception as e:
            logger.warning("C5联动 更新画像 risk_flag(MySQL) 失败: %s", e)

        # 2. 设置 Redis 风险标记 + 清除画像缓存
        try:
            from app.config.database import get_redis
            r = await get_redis()
            await r.set(f"risk_flag:{customer_id}", risk_flag, ex=86400)
            await r.delete(f"profile:{customer_id}")
            logger.info(
                "C5联动(Redis): 客户%s risk_flag=%s + 缓存已清除",
                customer_id, risk_flag,
            )
        except Exception as e:
            logger.warning("C5联动 Redis 操作失败(不影响MySQL更新): %s", e)


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
