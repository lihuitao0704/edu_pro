"""
业务操作 Agent — NL2API
负责人: LHG
功能: 自然语言 → 意图识别 → 参数提取 → 权限校验 → 执行操作
P0: 支持 产品申购 + 产品查询 两种意图
"""

import os
import uuid
import json
import httpx
from typing import Optional

from openai import AsyncOpenAI

from app.config.settings import get_settings
from app.api.operations.purchase import purchase_product
from app.api.operations.product_query import query_product, list_products
from app.api.operations.redeem import redeem_product
from app.api.operations.transfer import transfer_funds
from app.api.operations.assessment import redo_assessment
from app.api.operations.contact import update_contact
from app.api.operations.suspicious_report import report_suspicious
from app.api.operations.workorder import create_work_order
from app.tool.graph_query_tool import (
    get_customer_products,
    get_suitable_products,
    get_product_industry,
    resolve_customer_id,
    resolve_product_id,
)
from app.service.event_bus import publish_operation_event
from app.memory.session_memory import SessionMemory
from app.utils.data_masking import mask_text

settings = get_settings()

# ==================== 业务常量 ====================

_MAX_AMOUNT = 10_000_000  # 单笔金额上限 1000 万


def _safe_float(value, field: str = "金额") -> tuple[float, Optional[str]]:
    """安全转换为 float，失败时返回 (0.0, 错误信息)"""
    try:
        v = float(value)
        if v <= 0:
            return 0.0, f"{field}必须大于0"
        if v > _MAX_AMOUNT:
            return 0.0, f"{field}超过上限（{_MAX_AMOUNT}元）"
        return v, None
    except (ValueError, TypeError):
        return 0.0, f"{field}格式错误（无法转为数字）"


# ==================== LLM 客户端 ====================

# 使用 AsyncOpenAI 异步客户端，避免阻塞事件循环
_http_client = httpx.AsyncClient(trust_env=False, timeout=settings.llm.openai_timeout)

llm_client = AsyncOpenAI(
    api_key=settings.llm.openai_api_key,
    base_url=settings.llm.openai_base_url,
    timeout=settings.llm.openai_timeout,
    max_retries=3,  # 修复：LLM API临时故障时自动重试，提升稳定性
    http_client=_http_client,
)

# ==================== 二次确认 Redis 状态管理 ====================

_CONFIRM_PREFIX = "confirm:pending:"
_CONFIRM_TTL = 120  # 120 秒有效


async def _save_pending_confirm(session_id: str, action: str, arguments: dict,
                                 user_id: int, user_role: str) -> bool:
    """将待确认操作存入 Redis，等待用户确认。返回是否保存成功。"""
    try:
        from app.config.database import get_redis
        r = await get_redis()
        summary = _build_confirmation_summary(action, arguments)
        await r.setex(
            f"{_CONFIRM_PREFIX}{session_id}",
            _CONFIRM_TTL,
            json.dumps({"action": action, "arguments": arguments,
                        "user_id": user_id, "user_role": user_role,
                        "summary": summary}),
        )
        return True
    except Exception:
        return False  # Redis 不可用，调用方应拒绝进入确认流程


async def _load_pending_confirm(session_id: str) -> Optional[dict]:
    """读取 Redis 中的待确认操作"""
    try:
        from app.config.database import get_redis
        r = await get_redis()
        data = await r.get(f"{_CONFIRM_PREFIX}{session_id}")
        if data:
            return json.loads(data)
    except Exception:
        pass
    return None


async def _delete_pending_confirm(session_id: str):
    """删除 Redis 中的待确认记录（确认/取消后调用）"""
    try:
        from app.config.database import get_redis
        r = await get_redis()
        await r.delete(f"{_CONFIRM_PREFIX}{session_id}")
    except Exception:
        pass


def _build_confirmation_summary(action: str, arguments: dict) -> str:
    """
    生成待确认操作的自然语言摘要，用于：
    1. 展示给用户明确确认内容（避免盲目确认）
    2. 存入 Redis，确认时校验一致性
    """
    if action == "purchase_product":
        return (f"申购：客户 {arguments.get('customer_name','')} "
                f"购买 {arguments.get('product_name','')}，"
                f"金额 {arguments.get('amount', 0)} 元")
    if action == "redeem_product":
        return (f"赎回：客户 {arguments.get('customer_name','')} "
                f"赎回 {arguments.get('product_name','')}，"
                f"份额 {arguments.get('shares', 0)}")
    if action == "transfer_funds":
        return (f"转账：{arguments.get('from_customer_name','')} → "
                f"{arguments.get('to_customer_name','')}，"
                f"金额 {arguments.get('amount', 0)} 元")
    return f"执行 {action}，参数 {arguments}"

# ==================== RBAC 权限矩阵 ====================

# 角色 → 允许的操作
RBAC_PERMISSIONS = {
    "理财顾问": ["purchase_product", "redeem_product", "transfer_funds", "redo_assessment", "query_product", "query_product_list", "get_customer_holdings", "get_suitable_products"],
    "客户经理": ["update_contact", "create_work_order", "query_product", "query_product_list", "get_customer_holdings"],
    "风控专员": ["report_suspicious", "query_product", "query_product_list"],
    "管理员": ["purchase_product", "redeem_product", "transfer_funds", "redo_assessment", "update_contact",
              "query_product", "query_product_list", "get_customer_holdings", "get_suitable_products", "report_suspicious", "create_work_order"],
}

# 二次确认阈值
CONFIRM_THRESHOLDS = {
    "purchase_product": 10000,    # 申购 > 1万 需确认
    "redeem_product": 10000,      # 赎回 > 1万 需确认
    "transfer_funds": 50000,      # 转账 > 5万 需确认
}

# ==================== Function Calling Tool 定义 ====================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "purchase_product",
            "description": "帮客户申购基金产品。需要指定客户姓名、产品名称和申购金额",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "客户姓名"},
                    "product_name": {"type": "string", "description": "产品名称"},
                    "amount": {"type": "number", "description": "申购金额（元）"},
                },
                "required": ["customer_name", "product_name", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "redeem_product",
            "description": "帮客户赎回基金产品。需要指定客户姓名、产品名称和赎回份额",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "客户姓名"},
                    "product_name": {"type": "string", "description": "产品名称"},
                    "shares": {"type": "number", "description": "赎回份额"},
                },
                "required": ["customer_name", "product_name", "shares"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transfer_funds",
            "description": "帮客户转账。需要指定转出客户、转入客户和金额",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_customer_name": {"type": "string", "description": "转出客户姓名"},
                    "to_customer_name": {"type": "string", "description": "转入客户姓名"},
                    "amount": {"type": "number", "description": "转账金额（元）"},
                },
                "required": ["from_customer_name", "to_customer_name", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "redo_assessment",
            "description": "给客户重新做风险评估。需要传入客户在各评分题上的作答（整数列表），如未提供答案请先询问客户完成问卷",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "客户姓名"},
                    "answers": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "客户在各评分题上的作答（整数列表，每题1-20分）",
                    },
                },
                "required": ["customer_name", "answers"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_contact",
            "description": "更新客户的联系信息（手机号、邮箱等）",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "客户姓名"},
                    "field": {"type": "string", "description": "字段名: phone/email"},
                    "value": {"type": "string", "description": "新值"},
                },
                "required": ["customer_name", "field", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_product",
            "description": "查询某只基金的详细信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string", "description": "产品名称"},
                },
                "required": ["product_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_product_list",
            "description": "查询在售产品列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "risk_level": {"type": "string", "description": "风险等级 R1-R5，可选"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_holdings",
            "description": "查询客户当前持仓",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "客户姓名"},
                },
                "required": ["customer_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_suitable_products",
            "description": "根据风险等级查询适当性匹配的产品",
            "parameters": {
                "type": "object",
                "properties": {
                    "risk_level": {"type": "string", "description": "风险等级 R1-R5"},
                },
                "required": ["risk_level"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_suspicious",
            "description": "上报客户可疑交易",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "客户姓名"},
                    "reason": {"type": "string", "description": "可疑原因"},
                },
                "required": ["customer_name", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_work_order",
            "description": "为客户创建业务工单",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "客户姓名"},
                    "order_type": {"type": "string", "description": "工单类型: 投诉/建议/咨询"},
                    "content": {"type": "string", "description": "工单内容"},
                },
                "required": ["customer_name", "content"],
            },
        },
    },
]

# ==================== 系统提示词 ====================

SYSTEM_PROMPT = """你是智能财富管家系统的业务操作助手。你的职责是：
1. 理解用户的自然语言指令，识别业务意图
2. 提取操作所需的参数
3. 调用对应的工具函数执行操作

你可以执行以下操作：
- purchase_product: 帮客户申购基金产品
- redeem_product: 帮客户赎回基金产品
- transfer_funds: 帮客户转账
- redo_assessment: 给客户重新做风险评估（需先收集客户答案）
- update_contact: 更新客户联系信息（手机号/邮箱）
- query_product: 查询某只产品的详细信息
- query_product_list: 查询在售产品列表
- get_customer_holdings: 查询客户持仓
- get_suitable_products: 查询适当性匹配的产品
- report_suspicious: 上报可疑交易
- create_work_order: 为客户创建工单

注意事项：
- 如果参数不完整，请礼貌地询问用户补充
- 申购/赎回/转账等金融操作前应先确认信息
- 对于大额操作，需要提醒用户确认
- 风险评估（redo_assessment）需要先向客户出示问卷题目并收集答案（整数列表），再将答案传入answers参数执行
"""


def check_permission(user_role: str, action: str) -> bool:
    """RBAC 权限校验"""
    allowed = RBAC_PERMISSIONS.get(user_role, [])
    return action in allowed


def needs_confirmation(action: str, amount: float = 0) -> bool:
    """检查是否需要二次确认（仅对阈值表中的操作生效）"""
    if action not in CONFIRM_THRESHOLDS:
        return False  # 未配置阈值的操作（如查询类）无需确认
    return amount > CONFIRM_THRESHOLDS[action]


async def execute_tool(tool_name: str, arguments: dict, operator_id: int = None) -> dict:
    """执行工具函数"""
    if tool_name == "purchase_product":
        customer_name = arguments.get("customer_name", "")
        product_name = arguments.get("product_name", "")
        amount, err = _safe_float(arguments.get("amount", 0), "申购金额")
        if err:
            return {"success": False, "message": err}

        # 解析 ID
        customer_id = await resolve_customer_id(customer_name)
        if not customer_id:
            return {"success": False, "message": f"未找到客户: {customer_name}"}

        product_id = await resolve_product_id(product_name)
        if not product_id:
            return {"success": False, "message": f"未找到产品: {product_name}"}

        # 调用申购接口（需要传入 db session，这里简化处理）
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            result = await purchase_product(
                body={
                    "customer_id": customer_id,
                    "product_id": product_id,
                    "amount": amount,
                    "operator_id": operator_id,
                },
                db=db,
            )
            return {
                "success": result.code == 200,
                "message": result.message,
                "data": result.data,
            }

    elif tool_name == "query_product":
        product_name = arguments.get("product_name", "")
        product_id = await resolve_product_id(product_name)
        if not product_id:
            return {"success": False, "message": f"未找到产品: {product_name}"}

        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            result = await query_product(product_id=product_id, db=db)
            return {
                "success": result.code == 200,
                "message": result.message,
                "data": result.data,
            }

    elif tool_name == "query_product_list":
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            result = await list_products(
                risk_level=arguments.get("risk_level"),
                product_type=arguments.get("product_type"),
                db=db,
            )
            return {
                "success": result.get("code") == 200 if isinstance(result, dict) else result.code == 200,
                "data": result.get("data") if isinstance(result, dict) else result.data,
            }

    elif tool_name == "get_customer_holdings":
        customer_name = arguments.get("customer_name", "")
        found, data = await get_customer_products(customer_name)
        if not found:
            return {"success": False, "message": data}  # data 是错误信息字符串
        if not data:
            return {"success": False, "message": f"客户 {customer_name} 无持仓记录"}
        return {"success": True, "data": data}

    elif tool_name == "get_suitable_products":
        risk_level = arguments.get("risk_level", "R3")
        products = await get_suitable_products(risk_level)
        return {"success": True, "data": products}

    elif tool_name == "redeem_product":
        customer_name = arguments.get("customer_name", "")
        product_name = arguments.get("product_name", "")
        shares, err = _safe_float(arguments.get("shares", 0), "赎回份额")
        if err:
            return {"success": False, "message": err}
        customer_id = await resolve_customer_id(customer_name)
        if not customer_id:
            return {"success": False, "message": f"未找到客户: {customer_name}"}
        product_id = await resolve_product_id(product_name)
        if not product_id:
            return {"success": False, "message": f"未找到产品: {product_name}"}
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            result = await redeem_product(body={"customer_id": customer_id, "product_id": product_id, "shares": shares, "operator_id": operator_id}, db=db)
            return {"success": result.code == 200, "message": result.message, "data": result.data}

    elif tool_name == "transfer_funds":
        from_name = arguments.get("from_customer_name", "")
        to_name = arguments.get("to_customer_name", "")
        amount, err = _safe_float(arguments.get("amount", 0), "转账金额")
        if err:
            return {"success": False, "message": err}
        from_id = await resolve_customer_id(from_name)
        to_id = await resolve_customer_id(to_name)
        if not from_id:
            return {"success": False, "message": f"未找到转出客户: {from_name}"}
        if not to_id:
            return {"success": False, "message": f"未找到转入客户: {to_name}"}
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            result = await transfer_funds(body={"from_customer_id": from_id, "to_customer_id": to_id, "amount": amount, "operator_id": operator_id}, db=db)
            return {"success": result.code == 200, "message": result.message, "data": result.data}

    elif tool_name == "redo_assessment":
        customer_name = arguments.get("customer_name", "")
        answers = arguments.get("answers", [])
        customer_id = await resolve_customer_id(customer_name)
        if not customer_id:
            return {"success": False, "message": f"未找到客户: {customer_name}"}
        if not answers:
            return {"success": False, "message": "请先让客户完成风险评估问卷，获取答案后再执行风评重做"}
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            result = await redo_assessment(body={"customer_id": customer_id, "answers": answers, "operator_id": operator_id}, db=db)
            return {"success": result.code == 200, "message": result.message, "data": result.data}

    elif tool_name == "update_contact":
        customer_name = arguments.get("customer_name", "")
        field = arguments.get("field", "")
        value = arguments.get("value", "")
        customer_id = await resolve_customer_id(customer_name)
        if not customer_id:
            return {"success": False, "message": f"未找到客户: {customer_name}"}
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            result = await update_contact(body={"customer_id": customer_id, "field": field, "value": value}, db=db)
            return {"success": result.code == 200, "message": result.message, "data": result.data}

    elif tool_name == "report_suspicious":
        customer_name = arguments.get("customer_name", "")
        reason = arguments.get("reason", "")
        customer_id = await resolve_customer_id(customer_name)
        if not customer_id:
            return {"success": False, "message": f"未找到客户: {customer_name}"}
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            result = await report_suspicious(body={"customer_id": customer_id, "reason": reason, "reporter_id": operator_id}, db=db)
            return {"success": result.code == 200, "message": result.message, "data": result.data}

    elif tool_name == "create_work_order":
        customer_name = arguments.get("customer_name", "")
        order_type = arguments.get("order_type", "咨询")
        content = arguments.get("content", "")
        customer_id = await resolve_customer_id(customer_name)
        if not customer_id:
            return {"success": False, "message": f"未找到客户: {customer_name}"}
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            result = await create_work_order(body={"customer_id": customer_id, "order_type": order_type, "content": content, "submitter_id": operator_id}, db=db)
            return {"success": result.code == 200, "message": result.message, "data": result.data}

    return {"success": False, "message": f"未知工具: {tool_name}"}


async def operator_chat(
    message: str,
    session_id: str = "",
    user_id: int = 0,
    user_role: str = "理财顾问",
) -> dict:
    """
    业务操作 Agent 对话入口
    流程: 用户消息 → LLM意图识别+参数提取 → 权限校验 → 执行 → 返回结果
    """
    if not session_id:
        session_id = uuid.uuid4().hex

    # 会话记忆
    memory = SessionMemory(session_id)
    await memory.add_message("user", message)

    # 0. 检查是否有待确认的操作（用户回复"确认"或"取消"）
    msg_stripped = message.strip()
    if msg_stripped in ("确认", "确定", "是的", "好的", "y", "yes"):
        pending = await _load_pending_confirm(session_id)
        if pending:
            await _delete_pending_confirm(session_id)
            action = pending["action"]
            arguments = pending["arguments"]
            summary = pending.get("summary", _build_confirmation_summary(action, arguments))
            result = await execute_tool(action, arguments, operator_id=pending["user_id"])
            if result.get("success"):
                reply = f"✅ 已确认执行：{summary}\n\n" + _format_success_reply(action, arguments, result.get("data"))
                status = "ok"
            else:
                reply = f"❌ 确认操作执行失败：{summary}\n原因：{result.get('message', f'{action} 操作失败')}"
                status = "error"
            await memory.add_message("assistant", reply)
            return {"reply": reply, "action": action, "params": arguments,
                    "status": status, "session_id": session_id}
        else:
            reply = "没有待确认的操作，请问您需要办理什么业务？"
            await memory.add_message("assistant", reply)
            return {"reply": reply,
                    "action": None, "params": {}, "status": "ok", "session_id": session_id}

    if msg_stripped in ("取消", "不", "否", "n", "no"):
        pending = await _load_pending_confirm(session_id)
        if pending:
            await _delete_pending_confirm(session_id)
            reply = f"已取消 {pending['action']} 操作。"
            await memory.add_message("assistant", reply)
            return {"reply": reply,
                    "action": None, "params": {}, "status": "cancelled", "session_id": session_id}

    # 1. 前置权限校验：先确定该角色可用工具，再调用 LLM（避免浪费 token）
    allowed_actions = RBAC_PERMISSIONS.get(user_role, [])
    if not allowed_actions:
        reply = f"抱歉，角色（{user_role}）没有任何业务操作权限，请联系管理员。"
        await memory.add_message("assistant", reply)
        return {"reply": reply, "action": None, "params": {},
                "status": "permission_denied", "session_id": session_id}
    available_tools = [t for t in TOOLS if t["function"]["name"] in allowed_actions]

    # 2. 调用 LLM（Function Calling），附带历史上下文 + 仅可用工具
    history = await memory.get_messages(max_tokens=2048)
    # 历史中已包含刚加入的 user message，直接拼接系统提示词
    llm_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    try:
        response = await llm_client.chat.completions.create(
            model=settings.llm.openai_model_chat,
            messages=llm_messages,
            tools=available_tools,
            tool_choice="auto",
            temperature=settings.llm.openai_temperature,
        )
    except Exception as e:
        reply = f"抱歉，系统暂时无法处理您的请求: {e}"
        await memory.add_message("assistant", reply)
        return {
            "reply": reply,
            "action": None,
            "params": {},
            "status": "error",
            "session_id": session_id,
        }

    msg = response.choices[0].message

    # 3. 没有工具调用 → 普通对话回复
    if not msg.tool_calls:
        reply = mask_text(msg.content or "请问您需要办理什么业务？")
        await memory.add_message("assistant", reply)
        return {
            "reply": reply,
            "action": None,
            "params": {},
            "status": "ok",
            "session_id": session_id,
        }

    # 4. 处理所有工具调用（LLM 可能一次返回多个）
    replies = []
    actions_taken = []

    for tool_call in msg.tool_calls:
        action = tool_call.function.name
        try:
            arguments = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            replies.append(f"⚠️ 工具 {action} 参数解析失败，已跳过。")
            continue

        # 5. 防御性权限校验（工具已过滤，此处为兜底）
        if not check_permission(user_role, action):
            replies.append(f"抱歉，您的角色（{user_role}）没有执行 {action} 的权限")
            actions_taken.append({"action": action, "status": "permission_denied"})
            continue

        # 6. 二次确认检查（存入 Redis，等待用户确认）
        amount, amount_err = _safe_float(arguments.get("amount", 0), "金额")
        if amount_err and needs_confirmation(action, 0):
            # amount 非法但操作需要确认阈值，无法判断是否超阈值，拒绝
            replies.append(f"⚠️ {amount_err}，无法执行 {action}")
            actions_taken.append({"action": action, "status": "param_error"})
            continue
        if needs_confirmation(action, amount):
            saved = await _save_pending_confirm(session_id, action, arguments, user_id, user_role)
            if not saved:
                # Redis 不可用，无法保存确认状态，拒绝进入确认流程
                reply = f"系统暂忙，无法处理大额 {action} 操作，请稍后再试"
                replies.append(reply)
                actions_taken.append({"action": action, "status": "system_error"})
                continue
            summary = _build_confirmation_summary(action, arguments)
            # 拼接已处理的结果 + 确认提示
            pending_count = len(msg.tool_calls) - len(actions_taken) - 1  # 剩余未处理
            reply = (f"⚠️ 大额操作需确认：{summary}\n\n"
                     f"请回复 '确认' 执行，或 '取消' 放弃。")
            if replies:
                reply = "\n\n".join(replies) + "\n\n" + reply
            if pending_count > 0:
                reply += f"\n\n（另有 {pending_count} 个操作待处理，确认后将一并执行）"
            await memory.add_message("assistant", reply)
            return {
                "reply": reply,
                "action": action,
                "params": arguments,
                "status": "confirm_required",
                "session_id": session_id,
            }

        # 7. 执行工具
        result = await execute_tool(action, arguments, operator_id=user_id)
        actions_taken.append({"action": action, "params": arguments})

        # 8. 构造单条回复
        if result.get("success"):
            replies.append(_format_success_reply(action, arguments, result.get("data")))
            # 事件广播（成功操作后发布到 Redis Pub/Sub）
            await publish_operation_event(
                action=action,
                arguments=arguments,
                data=result.get("data", {}),
                user_id=user_id,
            )
        else:
            replies.append(result.get("message", f"{action} 操作失败"))

    combined_reply = mask_text("\n\n".join(replies)) if replies else "请问您需要办理什么业务？"
    final_status = "ok" if any(a.get("status") != "permission_denied" for a in actions_taken) else "permission_denied"

    await memory.add_message("assistant", combined_reply)

    return {
        "reply": combined_reply,
        "action": actions_taken[0]["action"] if actions_taken else None,
        "params": actions_taken[0].get("params", {}) if actions_taken else {},
        "status": final_status,
        "session_id": session_id,
    }


def _format_success_reply(action: str, arguments: dict, data: dict) -> str:
    """格式化成功回复"""
    if action == "purchase_product":
        return (
            f"✅ 申购成功！\n"
            f"• 交易流水号: {data.get('transaction_no', '')}\n"
            f"• 产品: {data.get('product_name', '')}\n"
            f"• 金额: {data.get('amount', 0)} 元\n"
            f"• 份额: {data.get('shares', 0)}\n"
            f"• 适用净值日期: {data.get('nav_date', '')}"
        )
    elif action == "query_product":
        return (
            f"📊 产品详情:\n"
            f"• 名称: {data.get('product_name', '')}\n"
            f"• 代码: {data.get('product_code', '')}\n"
            f"• 类型: {data.get('product_type', '')}\n"
            f"• 风险等级: {data.get('risk_level', '')}\n"
            f"• 预期收益: {data.get('expected_return', 0)}%\n"
            f"• 起投金额: {data.get('min_amount', 0)} 元\n"
            f"• 基金经理: {data.get('fund_manager', '')}"
        )
    elif action == "query_product_list":
        products = data if isinstance(data, list) else []
        if not products:
            return "当前没有符合条件的在售产品。"
        lines = ["📋 在售产品列表:"]
        for p in products[:5]:
            lines.append(
                f"• {p.get('product_name', '')} ({p.get('risk_level', '')}) "
                f"预期收益 {p.get('expected_return', 0)}%"
            )
        return "\n".join(lines)
    elif action == "get_customer_holdings":
        holdings = data if isinstance(data, list) else []
        if not holdings:
            return "该客户暂无持仓。"
        lines = ["💼 客户持仓:"]
        for h in holdings:
            lines.append(
                f"• {h.get('product_name', '')}: {h.get('shares', 0)} 份, "
                f"市值 {h.get('current_value', 0)} 元, 收益 {h.get('profit_ratio', 0)}%"
            )
        return "\n".join(lines)
    elif action == "get_suitable_products":
        products = data if isinstance(data, list) else []
        if not products:
            return "没有匹配的产品。"
        lines = ["🎯 适当性匹配产品:"]
        for p in products[:5]:
            lines.append(
                f"• {p.get('product_name', '')} ({p.get('risk_level', '')}) "
                f"预期收益 {p.get('expected_return', 0)}%"
            )
        return "\n".join(lines)
    elif action == "redeem_product":
        return (
            f"✅ 赎回成功！\n"
            f"• 交易流水号: {data.get('transaction_no', '')}\n"
            f"• 赎回份额: {data.get('shares', 0)}\n"
            f"• 到账金额: {data.get('amount', 0)} 元"
        )
    elif action == "transfer_funds":
        return (
            f"✅ 转账成功！\n"
            f"• 流水号: {data.get('transaction_no', '')}\n"
            f"• 金额: {data.get('amount', 0)} 元\n"
            f"• 转入客户ID: {data.get('to_customer_id', '')}"
        )
    elif action == "redo_assessment":
        return (
            f"✅ 风评完成！\n"
            f"• 客户ID: {data.get('customer_id', '')}\n"
            f"• 风险等级: {data.get('risk_level', '')}\n"
            f"• 评分: {data.get('score', 0)}\n"
            f"• 有效期至: {data.get('valid_until', '')}"
        )
    elif action == "update_contact":
        return f"✅ 信息更新成功！\n• 客户ID: {data.get('customer_id', '')}\n• 更新字段: {data.get('field', '')}"
    elif action == "report_suspicious":
        return f"✅ 可疑交易已上报！\n• 预警编号: {data.get('alert_no', '')}\n• 客户ID: {data.get('customer_id', '')}"
    elif action == "create_work_order":
        return f"✅ 工单创建成功！\n• 工单号: {data.get('work_order_no', '')}\n• 类型: {data.get('order_type', '')}"
    else:
        return f"操作 {action} 执行成功。"
