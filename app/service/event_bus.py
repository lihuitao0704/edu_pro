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
