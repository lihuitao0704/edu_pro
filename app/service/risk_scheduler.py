"""
风控周期校准任务（APScheduler）
===============================
每周日凌晨3点执行：置信度重算 + 过期预警标记
"""

import logging
from datetime import date, datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select, text, update

from app.config.database import async_session_factory
from app.model.entities import FinRiskAlert, RiskAssessment
from app.engine.confidence import ConfidenceCalculator

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler = None
_confidence = ConfidenceCalculator()


def _weekly_calibration():
    """每周日执行：重算所有待处理预警的置信度，标记过期预警"""
    import asyncio
    asyncio.run(_run_calibration())


async def _run_calibration():
    """异步执行校准逻辑"""
    async with async_session_factory() as db:
        # 查所有活跃预警
        result = await db.execute(
            select(FinRiskAlert).where(FinRiskAlert.status.in_(["未处理", "处理中", "pending"]))
        )
        alerts = result.scalars().all()

        updated = 0
        expired = 0
        now = datetime.now()

        for alert in alerts:
            if alert.create_time:
                age_days = (now - alert.create_time).days

                # 置信度时间衰减
                old_conf = alert.transaction_ids or {}
                evidence_count = len(old_conf.get("trigger_rules", []))
                new_conf = _confidence.calc_single(
                    source="ai_extract",
                    evidence_count=evidence_count,
                    created_at=alert.create_time,
                )

                # 低置信且超过180天 → 标记过期
                if new_conf < 0.3 and age_days > 180:
                    alert.status = "false_positive"
                    alert.handle_result = "系统周期校准: 置信度过低自动标记为误排除"
                    alert.update_time = now
                    expired += 1
                else:
                    # 更新 transaction_ids 里的置信度
                    tx_ids = alert.transaction_ids or {}
                    tx_ids["confidence"] = round(new_conf, 3)
                    tx_ids["last_calibration"] = now.isoformat()
                    alert.transaction_ids = tx_ids
                    alert.update_time = now
                    updated += 1

        # === SLA 超时自动升级 ===
        sla_rules = [
            ("low", 7, "medium", "超过7天未处理，自动升级为黄色预警"),
            ("medium", 3, "high", "超过3天未处理，自动升级为红色预警"),
        ]
        sla_upgraded = 0
        for alert in alerts:
            if alert.create_time and alert.status in ("pending",):
                days_pending = (now - alert.create_time).days
                for level, days_limit, new_level, reason in sla_rules:
                    if alert.alert_level == level and days_pending > days_limit:
                        alert.alert_level = new_level
                        old_summary = alert.trigger_detail or ""
                        alert.trigger_detail = f"{old_summary} | SLA超时: {reason}"
                        alert.update_time = now
                        sla_upgraded += 1
                        break

        # === 累计风险自动升级：30天内同一客户≥3次medium → 自动high ===
        from sqlalchemy import func
        from datetime import timedelta
        cutoff = now - timedelta(days=30)
        result = await db.execute(
            select(FinRiskAlert.customer_id, func.count(FinRiskAlert.id).label("cnt"))
            .where(FinRiskAlert.alert_level == "medium",
                   FinRiskAlert.create_time >= cutoff,
                   FinRiskAlert.status == "pending")
            .group_by(FinRiskAlert.customer_id)
            .having(func.count(FinRiskAlert.id) >= 3)
        )
        cumulative_upgraded = 0
        for row in result.fetchall():
            # 为这些客户自动创建一条 high 预警
            entity = FinRiskAlert(
                customer_id=row.customer_id,
                alert_type="cumulative_risk",
                alert_level="high",
                trigger_detail=f"近30天累计触发{row.cnt}次中风险预警，自动升级为高风险",
                transaction_ids={"cumulative_count": row.cnt, "upgrade_reason": "30天≥3次medium"},
                status="pending",
                create_time=now,
            )
            db.add(entity)
            cumulative_upgraded += 1

        await db.flush()
        logger.info(
            f"周期校准完成: 处理{len(alerts)}条, 过期{expired}条, "
            f"SLA升级{sla_upgraded}条, 累计升级{cumulative_upgraded}条, 更新{updated}条"
        )
        await db.commit()
        logger.info(f"周期校准完成: 处理{len(alerts)}条, 过期{expired}条, 更新{updated}条, 风评提醒{expiry_reminders}条")


async def _create_expiry_reminders(db) -> int:
    """Create one pending alert per customer for assessments expiring within 30 days."""
    today = date.today()
    deadline = today + timedelta(days=30)
    assessments = (await db.execute(
        select(RiskAssessment).where(RiskAssessment.valid_until.is_not(None))
    )).scalars().all()
    latest_by_customer = {}
    for assessment in assessments:
        current = latest_by_customer.get(assessment.customer_id)
        if current is None or assessment.create_time > current.create_time:
            latest_by_customer[assessment.customer_id] = assessment
    created = 0
    for assessment in latest_by_customer.values():
        if not today <= assessment.valid_until <= deadline:
            continue
        result = await db.execute(text("""
            INSERT IGNORE INTO fin_risk_alert
            (customer_id, alert_type, alert_level, trigger_detail, transaction_ids, reminder_key, status, create_time, update_time)
            VALUES (:customer_id, 'risk_assessment_expiring', 'medium', :detail, :payload, :reminder_key, 'pending', :now, :now)
        """), {
            "customer_id": assessment.customer_id,
            "reminder_key": f"risk_expiry:{assessment.id}",
            "detail": f"风险评估将于 {assessment.valid_until.isoformat()} 到期",
            "payload": __import__("json").dumps({"assessment_id": assessment.id, "valid_until": assessment.valid_until.isoformat()}),
            "now": datetime.now(),
        })
        created += int(result.rowcount or 0)
    return created


def start_scheduler():
    """启动周期校准任务（在 main.py 启动时调用）"""
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _weekly_calibration,
        'cron',
        day_of_week='sun',
        hour=3,
        minute=0,
        id='risk_weekly_calibration',
        name='风控置信度周期校准',
    )
    _scheduler.start()
    logger.info("风控周期校准已启动: 每周日 03:00")


def stop_scheduler():
    """停止周期校准"""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
