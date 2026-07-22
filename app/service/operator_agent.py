"""
业务操作 Agent — NL2API
负责人: LHG
功能: 自然语言 → 意图识别 → 参数提取 → 权限校验 → 执行操作
P0: 支持 产品申购 + 产品查询 两种意图
"""

import os
import uuid
import json
from typing import Optional

from openai import OpenAI

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

settings = get_settings()

# ==================== LLM 客户端 ====================

llm_client = OpenAI(
    api_key=settings.llm.openai_api_key,
    base_url=settings.llm.openai_base_url,
)

# ==================== RBAC 权限矩阵 ====================

# 角色 → 允许的操作
RBAC_PERMISSIONS = {
    "理财顾问": ["purchase_product", "redeem_product", "transfer_funds", "redo_assessment", "query_product", "query_product_list", "get_customer_holdings", "get_suitable_products"],
    "客户经理": ["update_contact_info", "create_work_order", "query_product", "query_product_list", "get_customer_holdings"],
    "风控专员": ["report_suspicious", "query_product", "query_product_list"],
    "管理员": ["purchase_product", "redeem_product", "transfer_funds", "redo_assessment", "update_contact_info",
              "query_product", "query_product_list", "get_customer_holdings", "get_suitable_products", "report_suspicious", "create_work_order"],
}

# 二次确认阈值
CONFIRM_THRESHOLDS = {
    "purchase_product": 10000,    # 申购 > 1万 需确认
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
            "description": "给客户重新做风险评估",
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
- redo_assessment: 给客户重新做风险评估
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
"""


def check_permission(user_role: str, action: str) -> bool:
    """RBAC 权限校验"""
    allowed = RBAC_PERMISSIONS.get(user_role, [])
    return action in allowed


def needs_confirmation(action: str, amount: float = 0) -> bool:
    """检查是否需要二次确认"""
    threshold = CONFIRM_THRESHOLDS.get(action, 0)
    return amount > threshold


async def execute_tool(tool_name: str, arguments: dict, operator_id: int = None) -> dict:
    """执行工具函数"""
    if tool_name == "purchase_product":
        customer_name = arguments.get("customer_name", "")
        product_name = arguments.get("product_name", "")
        amount = float(arguments.get("amount", 0))

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
        holdings = await get_customer_products(customer_name)
        if not holdings:
            return {"success": False, "message": f"客户 {customer_name} 无持仓记录"}
        return {"success": True, "data": holdings}

    elif tool_name == "get_suitable_products":
        risk_level = arguments.get("risk_level", "R3")
        products = await get_suitable_products(risk_level)
        return {"success": True, "data": products}

    elif tool_name == "redeem_product":
        customer_name = arguments.get("customer_name", "")
        product_name = arguments.get("product_name", "")
        shares = float(arguments.get("shares", 0))
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
        amount = float(arguments.get("amount", 0))
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
        customer_id = await resolve_customer_id(customer_name)
        if not customer_id:
            return {"success": False, "message": f"未找到客户: {customer_name}"}
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            result = await redo_assessment(body={"customer_id": customer_id, "answers": [1,2,3,4,5], "operator_id": operator_id}, db=db)
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

    # 1. 调用 LLM（Function Calling）
    try:
        response = llm_client.chat.completions.create(
            model=settings.llm.openai_model_chat,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            tools=TOOLS,
            tool_choice="auto",
            temperature=settings.llm.openai_temperature,
        )
    except Exception as e:
        return {
            "reply": f"抱歉，系统暂时无法处理您的请求: {e}",
            "action": None,
            "params": {},
            "status": "error",
            "session_id": session_id,
        }

    msg = response.choices[0].message

    # 2. 没有工具调用 → 普通对话回复
    if not msg.tool_calls:
        return {
            "reply": msg.content or "请问您需要办理什么业务？",
            "action": None,
            "params": {},
            "status": "ok",
            "session_id": session_id,
        }

    # 3. 处理工具调用
    tool_call = msg.tool_calls[0]
    action = tool_call.function.name
    try:
        arguments = json.loads(tool_call.function.arguments)
    except json.JSONDecodeError:
        arguments = {}

    # 4. RBAC 权限校验
    if not check_permission(user_role, action):
        return {
            "reply": f"抱歉，您的角色（{user_role}）没有执行 {action} 的权限",
            "action": action,
            "params": arguments,
            "status": "permission_denied",
            "session_id": session_id,
        }

    # 5. 二次确认检查
    amount = float(arguments.get("amount", 0))
    if needs_confirmation(action, amount):
        return {
            "reply": f"您即将执行 {action}，金额 {amount} 元，超过确认阈值。请确认是否继续？（回复'确认'执行）",
            "action": action,
            "params": arguments,
            "status": "confirm_required",
            "session_id": session_id,
        }

    # 6. 执行工具
    result = await execute_tool(action, arguments, operator_id=user_id)

    # 7. 构造回复
    if result.get("success"):
        reply = _format_success_reply(action, arguments, result.get("data"))
        status = "ok"
    else:
        reply = result.get("message", "操作失败")
        status = "error"

    return {
        "reply": reply,
        "action": action,
        "params": arguments,
        "status": status,
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
