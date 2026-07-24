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
from app.utils.circuit_breaker import CircuitBreaker, CircuitBreakerError

# 事件类型常量
EVENT_RISK_ALERT = "event:risk_alert"          # 向后兼容的通用频道
EVENT_C1_ADVISOR = "event:risk_alert:c1"       # C1: 投顾降权 — 高风险客户推荐降权
EVENT_C2_MONITOR = "event:risk_alert:c2"       # C2: 风控监测 — 规则触发/预警生成
EVENT_C4_CUSTOMER = "event:risk_alert:c4"      # C4: 客服联动 — 客服Agent风控提示
EVENT_PROFILE_UPDATE = "event:profile_update"
EVENT_WORK_ORDER_CHANGE = "event:work_order_change"

# 操作 → 事件类型映射（供 operator_agent 调用）
# 现在发布到分拆的频道 + 向后兼容的通用频道
ACTION_EVENT_MAP = {
    "purchase_product":  [EVENT_C1_ADVISOR, EVENT_C2_MONITOR, EVENT_C4_CUSTOMER],
    "redeem_product":    [EVENT_C1_ADVISOR, EVENT_C2_MONITOR, EVENT_C4_CUSTOMER],
    "transfer_funds":    [EVENT_C1_ADVISOR, EVENT_C2_MONITOR, EVENT_C4_CUSTOMER],
    "update_contact":    [EVENT_PROFILE_UPDATE],
    "create_work_order": [EVENT_WORK_ORDER_CHANGE],
    "redo_assessment":   [EVENT_PROFILE_UPDATE],
}

# 向后兼容: 所有C1/C2/C4事件也发布到通用频道(legacy订阅者)
_LEGACY_RISK_CHANNELS = {
    EVENT_C1_ADVISOR: EVENT_RISK_ALERT,
    EVENT_C2_MONITOR: EVENT_RISK_ALERT,
    EVENT_C4_CUSTOMER: EVENT_RISK_ALERT,
}

# 事件发布熔断器：失败3次后熔断，30秒后尝试恢复
_event_breaker = CircuitBreaker(fail_max=3, reset_timeout=30)


async def _save_failed_event(event_type: str, payload: dict, trace_id: str, error: str) -> None:
    """
    持久化失败的事件到MySQL（降级策略）
    当Redis不可用时，将事件保存到数据库，后续可以通过定时任务重试
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        from sqlalchemy import text
        from app.config.database import async_session_factory

        async with async_session_factory() as session:
            # 检查表是否存在，不存在则创建
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS event_failed_log (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    event_type VARCHAR(100) NOT NULL,
                    payload JSON NOT NULL,
                    trace_id VARCHAR(50),
                    error TEXT,
                    create_time DATETIME NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                    INDEX idx_status (status),
                    INDEX idx_create_time (create_time)
                )
            """))

            # 插入失败事件
            await session.execute(
                text("""
                    INSERT INTO event_failed_log
                    (event_type, payload, trace_id, error, create_time, status)
                    VALUES (:type, :payload, :trace, :error, NOW(), 'PENDING')
                """),
                {
                    "type": event_type,
                    "payload": json.dumps(payload, ensure_ascii=False),
                    "trace": trace_id,
                    "error": error[:500] if error else "",  # 限制错误信息长度
                }
            )
            await session.commit()
            logger.info(f"失败事件已持久化: {event_type}, trace_id={trace_id}")
    except Exception as e:
        logger.error(f"持久化失败事件异常: {e}")


async def publish_event(event_type: str, payload: dict, trace_id: str = "") -> None:
    """
    发布事件到 Redis Pub/Sub 频道
    修复 3.10：添加重试机制（最多 3 次，指数退避）+ 熔断机制
    失败时持久化到MySQL，避免事件丢失
    """
    import asyncio
    import logging
    logger = logging.getLogger(__name__)

    max_retries = 3
    retry_delay = 0.5  # 初始重试延迟（秒）

    async def _do_publish():
        """实际的发布逻辑（被熔断器保护）"""
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

    # 使用熔断器保护发布逻辑
    try:
        # 重试逻辑
        for attempt in range(max_retries + 1):
            try:
                await _event_breaker.call(_do_publish)
                return  # 发布成功，退出重试循环
            except CircuitBreakerError:
                # 熔断器打开，快速失败，持久化事件
                logger.warning(f"事件发布被熔断: {event_type}, trace_id={trace_id}")
                await _save_failed_event(event_type, payload, trace_id, "熔断器打开")
                return
            except Exception as e:
                if attempt < max_retries:
                    # 重试前等待（指数退避）
                    logger.warning(
                        f"事件发布失败 (尝试 {attempt + 1}/{max_retries}): {e}，{retry_delay}s 后重试"
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避
                else:
                    # 所有重试失败，持久化事件
                    logger.warning(f"事件发布最终失败 (已重试 {max_retries} 次): {e}")
                    await _save_failed_event(event_type, payload, trace_id, str(e))
    except Exception as e:
        logger.error(f"事件发布异常: {e}")
        await _save_failed_event(event_type, payload, trace_id, str(e))


async def publish_operation_event(action: str, arguments: dict, data: dict,
                                    user_id: int, trace_id: str = "") -> None:
    """
    便捷函数：根据操作名称自动选择事件类型并发布到对应频道
    在 execute_tool 成功路径调用

    频道拆分（C1/C2/C4 联动）：
    - C1: event:risk_alert:c1 → 投顾降权
    - C2: event:risk_alert:c2 → 风控监测
    - C4: event:risk_alert:c4 → 客服联动
    - 向后兼容：同时发布到 event:risk_alert (legacy)
    """
    event_types = ACTION_EVENT_MAP.get(action)
    if not event_types:
        return  # 无需广播的操作（query_product 等）

    payload = {
        "action": action,
        "arguments": arguments,
        "result": data,
        "operator_id": user_id,
    }

    # 发布到所有对应的分拆频道
    published_channels = set()
    for event_type in event_types:
        await publish_event(event_type, payload, trace_id)
        published_channels.add(event_type)

    # 向后兼容：同时发布到 legacy 通用频道
    for channel in published_channels:
        legacy = _LEGACY_RISK_CHANNELS.get(channel)
        if legacy:
            await publish_event(legacy, payload, trace_id)


# ═══════════════════════════════════════════════════════════
# 事件订阅消费者（阶段3：多Agent协作闭环）
# ═══════════════════════════════════════════════════════════

import logging
_subscriber_logger = logging.getLogger("event_bus.subscriber")


async def start_event_subscriber() -> None:
    """
    启动事件订阅消费者（作为后台 task 在 lifespan 中运行）

    订阅 channel（拆分 C1/C2/C4 联动）:
      - event:risk_alert:c1 → 投顾降权：更新客户画像 risk_flag(MySQL) + Redis风险标记(TTL) + 清除缓存
      - event:risk_alert:c2 → 风控监测：记录风控事件日志
      - event:risk_alert:c4 → 客服联动：更新客服侧风险上下文(Redis)
      - event:risk_alert     → legacy 通用频道（向后兼容）
      - event:profile_update → 清除画像缓存
      - event:work_order_change → 记录日志

    Redis 不可用或连接断开时自动重连（指数退避，最长 60s），不影响主服务。
    """
    import asyncio

    reconnect_delay = 1  # 初始重连延迟（秒）
    max_reconnect_delay = 60

    SUBSCRIBED_CHANNELS = [
        EVENT_C1_ADVISOR,
        EVENT_C2_MONITOR,
        EVENT_C4_CUSTOMER,
        EVENT_RISK_ALERT,       # legacy 通用频道
        EVENT_PROFILE_UPDATE,
        EVENT_WORK_ORDER_CHANGE,
    ]

    while True:
        try:
            from app.config.database import get_redis
            r = await get_redis()
            pubsub = r.pubsub()
            await pubsub.subscribe(*SUBSCRIBED_CHANNELS)
            _subscriber_logger.info(
                "事件订阅消费者已启动，监听 %d 个频道: %s",
                len(SUBSCRIBED_CHANNELS),
                ", ".join(SUBSCRIBED_CHANNELS),
            )
            reconnect_delay = 1  # 连接成功后重置延迟

            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        channel = message.get("channel", "")
                        if isinstance(channel, bytes):
                            channel = channel.decode("utf-8")
                        await _handle_event(data, channel)
                    except Exception as e:
                        _subscriber_logger.warning("事件处理异常: %s", e)

        except asyncio.CancelledError:
            _subscriber_logger.info("事件订阅消费者收到取消信号，正常退出")
            break
        except Exception as e:
            _subscriber_logger.warning(
                "事件订阅连接异常（%s 后重连）: %s", reconnect_delay, e
            )
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)


async def _handle_event(event: dict, channel: str = "") -> None:
    """分发事件到对应处理器（支持 C1/C2/C4 分拆频道）"""
    event_type = event.get("event_type", "")
    payload = event.get("payload", {})

    # 根据频道路由（优先使用频道名，因为同一个 event_type 可能出现在多个频道）
    if channel in (EVENT_C1_ADVISOR, EVENT_RISK_ALERT):
        # C1: 投顾降权 — 更新风险标记
        if channel == EVENT_C1_ADVISOR or event_type in (EVENT_C1_ADVISOR, EVENT_RISK_ALERT):
            await _handle_c1_advisor_downgrade(payload)
    if channel in (EVENT_C2_MONITOR, EVENT_RISK_ALERT):
        # C2: 风控监测 — 记录监测日志
        if channel == EVENT_C2_MONITOR or event_type in (EVENT_C2_MONITOR, EVENT_RISK_ALERT):
            await _handle_c2_risk_monitor(payload)
    if channel in (EVENT_C4_CUSTOMER, EVENT_RISK_ALERT):
        # C4: 客服联动 — 更新客服风险上下文
        if channel == EVENT_C4_CUSTOMER or event_type in (EVENT_C4_CUSTOMER, EVENT_RISK_ALERT):
            await _handle_c4_customer_context(payload)

    # 画像更新和工单变更按原逻辑处理
    if event_type == EVENT_PROFILE_UPDATE:
        await _handle_profile_update(payload)
    elif event_type == EVENT_WORK_ORDER_CHANGE:
        await _handle_work_order_change(payload)


async def _handle_c1_advisor_downgrade(payload: dict) -> None:
    """
    C1 频道处理：投顾降权
    联动逻辑（对应功能设计 §7.3 场景二）：
      风控Agent发布 risk_alert → 更新画像 risk_flag(MySQL+Redis) → 下次推荐时降权
    """
    await _handle_risk_alert(payload)


async def _handle_c2_risk_monitor(payload: dict) -> None:
    """
    C2 频道处理：风控监测日志
    记录风控事件详情，供风控管理页实时展示
    """
    import logging
    logger = logging.getLogger("event_bus.c2")

    customer_id = payload.get("arguments", {}).get("customer_id") or payload.get("result", {}).get("customer_id")
    action = payload.get("action", "unknown")
    amount = payload.get("arguments", {}).get("amount", 0)

    logger.info(
        "C2风控监测 | action=%s | customer_id=%s | amount=%s",
        action, customer_id, amount,
    )


async def _handle_c4_customer_context(payload: dict) -> None:
    """
    C4 频道处理：客服联动
    当客户触发风控事件后，更新 Redis 中的客服侧风险上下文，
    供客服Agent在对话中读取并展示风控提示

    联动逻辑：
      交易事件 → 风控标记 → Redis 上下文 → 客服Agent读取 → 风控提示
    """
    import logging
    logger = logging.getLogger("event_bus.c4")

    customer_id = None
    # 从多处提取 customer_id
    args = payload.get("arguments", {})
    result = payload.get("result", {})
    customer_id = args.get("customer_id") or result.get("customer_id")

    if customer_id:
        try:
            from app.config.database import get_redis
            r = await get_redis()
            context_key = f"cs_risk_ctx:{customer_id}"
            risk_data = {
                "has_alert": True,
                "last_action": payload.get("action", ""),
                "amount": args.get("amount", 0),
                "updated_at": datetime.now().isoformat(),
                "source": "c4_event",
            }
            await r.set(context_key, json.dumps(risk_data, ensure_ascii=False), ex=86400)  # 24h TTL
            logger.info(
                "C4客服联动: 客户%s 风险上下文已更新(Redis) | action=%s",
                customer_id, payload.get("action", ""),
            )
        except Exception as e:
            logger.warning("C4客服联动 Redis 写入失败: %s", e)


async def _handle_risk_alert(payload: dict) -> None:
    """
    处理风控预警事件 → 更新客户画像 risk_flag(MySQL) + Redis风险标记(TTL) + 清除缓存

    联动逻辑（对应功能设计 §7.3 场景二）：
      风控Agent发布 risk_alert → 更新画像风险标记(MySQL+Redis) → 下次推荐时降权
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
            "风控联动(MySQL): 客户%s 画像 risk_flag 更新为 %s", customer_id, risk_flag
        )
    except Exception as e:
        _subscriber_logger.warning("更新画像 risk_flag(MySQL) 失败: %s", e)

    # 2. 设置 Redis 风险标记 + 清除画像缓存
    try:
        from app.config.database import get_redis
        r = await get_redis()
        # Redis 风险标记（含 TTL，供 AdvisorService._check_risk_flag() 实时查询）
        await r.set(f"risk_flag:{customer_id}", risk_flag, ex=86400)  # 24h TTL
        # 清除画像缓存（下次读取自动回源拿最新 risk_flag）
        await r.delete(f"profile:{customer_id}")
        _subscriber_logger.info(
            "风控联动(Redis): 客户%s risk_flag=%s (TTL=24h) + 缓存已清除",
            customer_id, risk_flag,
        )
    except Exception as e:
        _subscriber_logger.warning("Redis 操作失败(不影响MySQL更新): %s", e)


async def _handle_profile_update(payload: dict) -> None:
    """
    处理画像更新事件 → 清除相关客户画像缓存。

    联动逻辑：客户信息更新（联系方式/重新评估）→ 清除缓存 → 下次读取拿最新数据。
    """
    customer_id = payload.get("arguments", {}).get("customer_id")
    if not customer_id:
        return

    try:
        from app.config.database import get_redis
        r = await get_redis()
        await r.delete(f"profile:{customer_id}")
        _subscriber_logger.info("画像更新联动: 客户%s 缓存已清除", customer_id)
    except Exception as e:
        _subscriber_logger.warning("画像缓存清除失败: %s", e)


async def _handle_work_order_change(payload: dict) -> None:
    """
    处理工单变更事件 → 记录日志（预留扩展点）。

    后续可扩展：工单创建 → 通知客户经理、更新客户画像服务记录等。
    """
    customer_id = payload.get("arguments", {}).get("customer_id")
    action = payload.get("action", "unknown")
    _subscriber_logger.info(
        "工单变更事件 | customer_id=%s | action=%s", customer_id, action
    )
