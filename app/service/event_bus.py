"""
事件广播 — Redis Pub/Sub
业务操作执行后广播事件，供风控 Agent、投顾 Agent 等订阅

事件类型:
    event:risk_alert       → 申购 / 赎回 / 转账（风控 Agent 订阅）
    event:profile_update   → 信息更新（投顾 / 客服 Agent 订阅）
    event:work_order_change → 工单创建

消息体:
    {event_type, source_agent, payload, timestamp, trace_id}

负责人: LHG
"""

import json
import uuid
from datetime import datetime

# 事件类型常量
EVENT_RISK_ALERT = "event:risk_alert"
EVENT_PROFILE_UPDATE = "event:profile_update"
EVENT_WORK_ORDER_CHANGE = "event:work_order_change"

# 操作 → 事件类型映射（供 operator_agent 调用）
ACTION_EVENT_MAP = {
    "purchase_product":  EVENT_RISK_ALERT,
    "redeem_product":    EVENT_RISK_ALERT,
    "transfer_funds":    EVENT_RISK_ALERT,
    "update_contact":    EVENT_PROFILE_UPDATE,
    "create_work_order": EVENT_WORK_ORDER_CHANGE,
    "redo_assessment":   EVENT_PROFILE_UPDATE,
}


async def publish_event(event_type: str, payload: dict, trace_id: str = "") -> None:
    """
    发布事件到 Redis Pub/Sub 频道
    Redis 不可用时静默失败（降级），不影响主业务
    """
    try:
        from app.config.database import get_redis
        r = await get_redis()
        message = {
            "event_type": event_type,
            "source_agent": "operator",
            "payload": payload,
            "timestamp": datetime.now().isoformat(),
            "trace_id": trace_id or uuid.uuid4().hex[:8],
        }
        await r.publish(event_type, json.dumps(message, ensure_ascii=False))
    except Exception:
        # Redis 不可用时降级：仅忽略，不阻塞主流程
        pass


async def publish_operation_event(action: str, arguments: dict, data: dict,
                                    user_id: int, trace_id: str = "") -> None:
    """
    便捷函数：根据操作名称自动选择事件类型并发布
    在 execute_tool 成功路径调用
    """
    event_type = ACTION_EVENT_MAP.get(action)
    if not event_type:
        return  # 无需广播的操作（query_product 等）

    payload = {
        "action": action,
        "arguments": arguments,
        "result": data,
        "operator_id": user_id,
    }
    await publish_event(event_type, payload, trace_id)


# ═══════════════════════════════════════════════════════════
# 事件订阅消费者（阶段3：多Agent协作闭环）
# ═══════════════════════════════════════════════════════════

import logging
_subscriber_logger = logging.getLogger("event_bus.subscriber")


async def start_event_subscriber() -> None:
    """
    启动事件订阅消费者（作为后台 task 在 lifespan 中运行）

    订阅 channel:
      - event:risk_alert → 更新客户画像 risk_flag（投顾/客服联动）
    Redis 不可用时静默退出，不影响主服务。
    """
    try:
        from app.config.database import get_redis
        r = await get_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe(EVENT_RISK_ALERT)
        _subscriber_logger.info("事件订阅消费者已启动，监听: %s", EVENT_RISK_ALERT)

        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    await _handle_event(data)
                except Exception as e:
                    _subscriber_logger.warning("事件处理异常: %s", e)
    except Exception as e:
        _subscriber_logger.warning("事件订阅启动失败(不影响主服务): %s", e)


async def _handle_event(event: dict) -> None:
    """分发事件到对应处理器"""
    event_type = event.get("event_type")
    payload = event.get("payload", {})

    if event_type == EVENT_RISK_ALERT:
        await _handle_risk_alert(payload)
    else:
        _subscriber_logger.debug("未处理的事件类型: %s", event_type)


async def _handle_risk_alert(payload: dict) -> None:
    """
    处理风控预警事件 → 更新客户画像 risk_flag + 清除缓存

    联动逻辑（对应功能设计 §7.3 场景二）：
      风控Agent发布 risk_alert → 投顾Agent更新画像风险标记 → 下次推荐时降权
    """
    customer_id = payload.get("customer_id")
    alert_level = payload.get("alert_level", "medium")
    if not customer_id:
        return

    risk_flag = "high" if alert_level == "high" else "warning"

    # 1. 更新 MySQL 画像 risk_flag
    try:
        from sqlalchemy import text
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            await db.execute(
                text("UPDATE fin_customer_profile SET risk_flag = :flag WHERE customer_id = :cid"),
                {"flag": risk_flag, "cid": customer_id},
            )
            await db.commit()
        _subscriber_logger.info(
            "风控联动: 客户%s 画像 risk_flag 更新为 %s", customer_id, risk_flag
        )
    except Exception as e:
        _subscriber_logger.warning("更新画像 risk_flag 失败: %s", e)

    # 2. 清除 Redis 画像缓存（下次读取自动回源拿最新 risk_flag）
    try:
        from app.config.database import get_redis
        r = await get_redis()
        await r.delete(f"profile:{customer_id}")
    except Exception:
        pass
