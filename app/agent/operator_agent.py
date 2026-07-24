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
    resolve_customer_id,
    resolve_product_id,
)
from app.service.event_bus import publish_operation_event
from app.memory.session_memory import SessionMemory
from app.utils.data_masking import mask_text
from sqlalchemy import text
from decimal import Decimal

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


# ==================== P0 业务校验辅助函数 ====================

# 适当性匹配矩阵：客户风险等级 → 可购买产品风险等级
_SUITABILITY_MAP = {
    "C1": ["R1"],                           # 保守型 → 仅 R1
    "C2": ["R1", "R2"],                     # 稳健型 → R1, R2
    "C3": ["R1", "R2", "R3"],               # 平衡型 → R1-R3
    "C4": ["R1", "R2", "R3", "R4"],         # 进取型 → R1-R4
    "C5": ["R1", "R2", "R3", "R4", "R5"],   # 激进型 → R1-R5
    # 兼容中文名
    "保守型": ["R1"],
    "稳健型": ["R1", "R2"],
    "平衡型": ["R1", "R2", "R3"],
    "进取型": ["R1", "R2", "R3", "R4"],
    "激进型": ["R1", "R2", "R3", "R4", "R5"],
}

# 中文名 → C编号 映射
_RISK_LEVEL_NORMALIZE = {
    "保守型": "C1", "稳健型": "C2", "平衡型": "C3", "进取型": "C4", "激进型": "C5",
    "R1": "C1", "R2": "C2", "R3": "C3", "R4": "C4", "R5": "C5",
}


async def _get_customer_risk_level(customer_id: int, db) -> Optional[str]:
    """查询客户风险等级（C1-C5），返回 None 表示未评估"""
    try:
        row = await db.execute(
            text("SELECT risk_level FROM fin_risk_assessment WHERE customer_id = :cid "
                 "ORDER BY create_time DESC LIMIT 1"),
            {"cid": customer_id},
        )
        row = row.mappings().first()
        if not row:
            return None
        level = row["risk_level"]
        # 标准化为 C1-C5 格式
        return _RISK_LEVEL_NORMALIZE.get(level, level)
    except Exception:
        return None


async def _get_product_risk_level(product_id: int, db) -> Optional[str]:
    """查询产品风险等级（R1-R5）"""
    try:
        row = await db.execute(
            text("SELECT risk_level FROM fin_product WHERE id = :pid"),
            {"pid": product_id},
        )
        row = row.mappings().first()
        if not row:
            return None
        return row["risk_level"]
    except Exception:
        return None


async def _check_suitability(customer_id: int, product_id: int, db) -> Optional[str]:
    """
    适当性校验：客户风险等级是否匹配产品风险等级
    返回 None 表示通过，否则返回错误信息字符串
    """
    customer_level = await _get_customer_risk_level(customer_id, db)
    if not customer_level:
        return "客户尚未完成风险评估，请先完成风评"

    product_level = await _get_product_risk_level(product_id, db)
    if not product_level:
        return None  # 产品信息获取失败，跳过校验（让下游接口处理）

    allowed_levels = _SUITABILITY_MAP.get(customer_level, [])
    if product_level not in allowed_levels:
        return (f"⚠️ 适当性不匹配：客户风险等级 {customer_level}，"
                f"产品风险等级 {product_level}，"
                f"允许购买 {', '.join(allowed_levels)} 级别产品")
    return None


async def _check_holdings(customer_id: int, product_id: int, shares: float, db) -> Optional[str]:
    """
    持仓校验：赎回前检查客户是否持有该产品且份额充足
    返回 None 表示通过，否则返回错误信息字符串
    """
    try:
        row = await db.execute(
            text("SELECT shares FROM fin_holdings "
                 "WHERE customer_id = :cid AND product_id = :pid AND status = '持有中'"),
            {"cid": customer_id, "pid": product_id},
        )
        row = row.mappings().first()
        if not row:
            return "客户未持有该产品，无法赎回"
        holding_shares = Decimal(str(row["shares"] or 0))
        redeem_shares = Decimal(str(shares))
        if redeem_shares > holding_shares:
            return f"赎回份额({shares})超过持有份额({holding_shares})"
    except Exception as e:
        return f"持仓查询失败: {e}"
    return None


async def _check_balance(customer_id: int, amount: float, db) -> Optional[str]:
    """
    余额校验：转账前检查转出方余额是否充足
    返回 None 表示通过，否则返回错误信息字符串
    """
    try:
        row = await db.execute(
            text("SELECT balance FROM sys_user WHERE id = :id"),
            {"id": customer_id},
        )
        row = row.mappings().first()
        if not row:
            return "未找到客户账户"
        balance = Decimal(str(row["balance"] or 0))
        transfer_amount = Decimal(str(amount))
        if transfer_amount > balance:
            return f"转出方余额不足：余额{balance}元，转账{amount}元"
    except Exception as e:
        return f"余额查询失败: {e}"
    return None


async def _check_customer_status(customer_id: int, db) -> Optional[str]:
    """
    客户状态校验：检查客户账户是否可操作
    返回 None 表示通过，否则返回错误信息字符串
    """
    try:
        row = await db.execute(
            text("SELECT status FROM sys_user WHERE id = :id"),
            {"id": customer_id},
        )
        row = row.mappings().first()
        if not row:
            return "未找到客户账户"
        status = row["status"]
        if status != "正常":
            return f"客户账户状态异常：{status}，无法执行操作"
    except Exception as e:
        return f"客户状态查询失败: {e}"
    return None


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

# 角色 → 允许的操作（精简版：只保留核心业务操作）
RBAC_PERMISSIONS = {
    "理财顾问": ["purchase_product", "redeem_product", "transfer_funds", "redo_assessment",
                "query_product", "query_product_list", "get_customer_holdings", "get_suitable_products",
                "query_audit_log", "query_customer_panoramic", "query_customer_list"],
    "客户经理": ["update_contact", "create_work_order", "query_product", "query_product_list",
                "get_customer_holdings", "query_audit_log", "query_customer_panoramic",
                "query_customer_list"],
    "风控专员": ["report_suspicious", "query_product", "query_product_list",
                "query_audit_log", "query_customer_panoramic", "query_customer_list"],
    "管理员": ["purchase_product", "redeem_product", "transfer_funds", "redo_assessment", "update_contact",
              "query_product", "query_product_list", "get_customer_holdings", "get_suitable_products",
              "report_suspicious", "create_work_order",
              "query_audit_log", "query_customer_panoramic", "query_customer_list"],
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
    # ==================== 审计日志查询工具（内部审计需求） ====================
    {
        "type": "function",
        "function": {
            "name": "query_audit_log",
            "description": "查询客户操作审计日志（申购/赎回/转账记录）。用于内部审计和合规检查",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "客户姓名（可选，不填则查询所有客户）"},
                    "transaction_type": {"type": "string", "description": "操作类型：purchase/redeem/transfer（可选）"},
                    "min_amount": {"type": "number", "description": "最小金额（可选，用于查询大额操作）"},
                    "days": {"type": "integer", "description": "查询天数范围，默认30天"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_customer_panoramic",
            "description": "查询客户全景视图（一站式展示客户基本信息、持仓、近期操作、风险标记）。用于内部员工全面了解客户状况",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "客户姓名"},
                },
                "required": ["customer_name"],
            },
        },
    },
    # ==================== 客户管理工具（内部员工使用） ====================
    {
        "type": "function",
        "function": {
            "name": "query_customer_list",
            "description": "查询系统中的客户列表。用于内部员工查看有哪些客户",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "返回数量限制，默认50"},
                    "risk_level": {"type": "string", "description": "按风险等级筛选：C1/C2/C3/C4/C5（可选）"},
                    "status": {"type": "string", "description": "按状态筛选：正常/冻结（可选）"},
                },
            },
        },
    },
]

# ==================== 系统提示词 ====================

SYSTEM_PROMPT = """你是智能财富管家系统的**业务操作助手**，面向内部人员（理财顾问、客户经理、风控专员、管理员）。

你的核心职责：
1. 协助内部人员执行客户业务操作（申购、赎回、转账、风评等）
2. **自动执行合规校验**（适当性匹配、持仓检查、余额检查、客户状态检查）
3. 查询客户信息、产品详情、审计日志等

你可以执行以下操作：
- purchase_product: 帮客户申购基金产品（会自动校验适当性匹配）
- redeem_product: 帮客户赎回基金产品（会自动校验持仓是否充足）
- transfer_funds: 帮客户转账（会自动校验余额是否充足）
- redo_assessment: 给客户重新做风险评估
- update_contact: 更新客户联系信息
- query_product: 查询某只产品的详细信息
- query_product_list: 查询在售产品列表
- get_customer_holdings: 查询客户持仓
- get_suitable_products: 根据风险等级查询适当性匹配的产品
- report_suspicious: 上报可疑交易
- create_work_order: 为客户创建工单
- query_audit_log: 查询客户操作审计日志（申购/赎回/转账记录）
- query_customer_panoramic: 查询客户全景视图（一站式展示客户全部信息）
- query_customer_list: 查询系统中的客户列表

客户识别规则（重要！）：
- "演示客户05"、"演示客户5" → customer_name 填 "演示客户05"（系统会自动提取编号5）
- "客户ID 5"、"客户ID：5"、"客户5" → customer_name 填 "客户ID 5"（系统会自动解析ID）
- "演示客户15" → customer_name 填 "演示客户15"（系统会自动提取编号15）
- 如果用户用纯数字ID指定客户，请用"客户ID N"格式

回复风格（面向内部人员）：
- 简洁、结构化、专业
- 使用 emoji 标记操作状态（✅ 成功 / ❌ 失败 / ⚠️ 预警）
- 操作失败时清晰说明原因（如"适当性不匹配"、"余额不足"、"持仓不足"）
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

        # P0 校验：客户状态 + 适当性匹配
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            status_err = await _check_customer_status(customer_id, db)
            if status_err:
                return {"success": False, "message": status_err}

            suitability_err = await _check_suitability(customer_id, product_id, db)
            if suitability_err:
                return {"success": False, "message": suitability_err}

        # 调用申购接口（需要传入 db session，这里简化处理）
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

        # P0 校验：客户状态 + 持仓充足
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            status_err = await _check_customer_status(customer_id, db)
            if status_err:
                return {"success": False, "message": status_err}

            holdings_err = await _check_holdings(customer_id, product_id, shares, db)
            if holdings_err:
                return {"success": False, "message": holdings_err}

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

        # P0 校验：转出方状态 + 余额充足 + 转入方状态
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            status_err = await _check_customer_status(from_id, db)
            if status_err:
                return {"success": False, "message": f"转出方{status_err}"}

            balance_err = await _check_balance(from_id, amount, db)
            if balance_err:
                return {"success": False, "message": balance_err}

            to_status_err = await _check_customer_status(to_id, db)
            if to_status_err:
                return {"success": False, "message": f"转入方{to_status_err}"}

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

        # P0 校验：客户状态
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            status_err = await _check_customer_status(customer_id, db)
            if status_err:
                return {"success": False, "message": status_err}

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

        # P0 校验：客户状态
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            status_err = await _check_customer_status(customer_id, db)
            if status_err:
                return {"success": False, "message": status_err}

        async with async_session_factory() as db:
            result = await update_contact(body={"customer_id": customer_id, "field": field, "value": value}, db=db)
            return {"success": result.code == 200, "message": result.message, "data": result.data}

    elif tool_name == "report_suspicious":
        customer_name = arguments.get("customer_name", "")
        reason = arguments.get("reason", "")
        customer_id = await resolve_customer_id(customer_name)
        if not customer_id:
            return {"success": False, "message": f"未找到客户: {customer_name}"}

        # P0 校验：客户状态
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            status_err = await _check_customer_status(customer_id, db)
            if status_err:
                return {"success": False, "message": status_err}

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

        # P0 校验：客户状态
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            status_err = await _check_customer_status(customer_id, db)
            if status_err:
                return {"success": False, "message": status_err}

        async with async_session_factory() as db:
            result = await create_work_order(body={"customer_id": customer_id, "order_type": order_type, "content": content, "submitter_id": operator_id}, db=db)
            return {"success": result.code == 200, "message": result.message, "data": result.data}

    # ==================== 审计日志查询工具 ====================

    elif tool_name == "query_audit_log":
        customer_name = arguments.get("customer_name", "")
        transaction_type = arguments.get("transaction_type", "")
        min_amount = arguments.get("min_amount", 0)
        days = arguments.get("days", 30)

        # 构建查询条件
        conditions = ["1=1"]
        params = {"days": days}

        if customer_name:
            customer_id = await resolve_customer_id(customer_name)
            if not customer_id:
                return {"success": False, "message": f"未找到客户: {customer_name}"}
            conditions.append("t.customer_id = :cid")
            params["cid"] = customer_id

        if transaction_type:
            conditions.append("t.transaction_type = :type")
            params["type"] = transaction_type

        if min_amount > 0:
            conditions.append("t.amount >= :min_amt")
            params["min_amt"] = min_amount

        where_clause = " AND ".join(conditions)

        # 查询交易记录
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            result = await db.execute(
                text(f"""
                    SELECT t.transaction_no, t.customer_id, t.product_id,
                           t.transaction_type, t.amount, t.shares, t.status,
                           t.operator_id, t.remark, t.create_time,
                           p.product_name, p.risk_level,
                           u.real_name AS operator_name
                    FROM fin_transaction t
                    LEFT JOIN fin_product p ON t.product_id = p.id
                    LEFT JOIN sys_user u ON t.operator_id = u.id
                    WHERE {where_clause}
                      AND t.create_time >= DATE_SUB(NOW(), INTERVAL :days DAY)
                    ORDER BY t.create_time DESC
                    LIMIT 100
                """),
                params,
            )
            rows = result.mappings().all()

        transactions = []
        for row in rows:
            transactions.append({
                "transaction_no": row["transaction_no"],
                "customer_id": row["customer_id"],
                "transaction_type": row["transaction_type"],
                "amount": float(row["amount"] or 0),
                "shares": float(row["shares"] or 0),
                "product_name": row["product_name"],
                "risk_level": row["risk_level"],
                "status": row["status"],
                "operator_name": row["operator_name"] or f"操作员{row['operator_id']}",
                "remark": row["remark"],
                "create_time": row["create_time"].strftime("%Y-%m-%d %H:%M:%S") if row["create_time"] else "",
            })

        return {
            "success": True,
            "data": {
                "customer_name": customer_name or "全部客户",
                "transaction_type": transaction_type or "全部类型",
                "min_amount": min_amount,
                "query_days": days,
                "transactions": transactions,
                "total_count": len(transactions),
            }
        }

    elif tool_name == "query_customer_panoramic":
        customer_name = arguments.get("customer_name", "")
        customer_id = await resolve_customer_id(customer_name)
        if not customer_id:
            return {"success": False, "message": f"未找到客户: {customer_name}"}

        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            # 1. 客户基本信息
            user_row = await db.execute(
                text("SELECT id, real_name, phone, email, balance, status, create_time "
                     "FROM sys_user WHERE id = :cid"),
                {"cid": customer_id},
            )
            user = user_row.mappings().first()
            if not user:
                return {"success": False, "message": f"未找到客户: {customer_name}"}

            # 2. 风险等级
            risk_level = await _get_customer_risk_level(customer_id, db)

            # 3. 客户画像（如果有）
            profile_row = await db.execute(
                text("SELECT risk_level, risk_score, total_assets, investment_experience, "
                     "confidence_score FROM fin_customer_profile WHERE customer_id = :cid"),
                {"cid": customer_id},
            )
            profile = profile_row.mappings().first()

            # 4. 持仓信息（从 Neo4j）
            found, holdings_data = await get_customer_products(customer_name)
            holdings = holdings_data if found and isinstance(holdings_data, list) else []
            total_holdings_value = sum(float(h.get("current_value", 0)) for h in holdings)

            # 5. 近期交易（近30天）
            tx_row = await db.execute(
                text("""
                    SELECT transaction_type, amount, create_time
                    FROM fin_transaction
                    WHERE customer_id = :cid
                      AND create_time >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                    ORDER BY create_time DESC
                    LIMIT 10
                """),
                {"cid": customer_id},
            )
            recent_txs = tx_row.mappings().all()

            # 6. 风控预警
            alert_row = await db.execute(
                text("""
                    SELECT alert_type, alert_level, status, create_time
                    FROM fin_risk_alert
                    WHERE customer_id = :cid
                    ORDER BY create_time DESC
                    LIMIT 5
                """),
                {"cid": customer_id},
            )
            alerts = alert_row.mappings().all()

        # 7. 关联客户（从 Neo4j 社区发现）
        similar = await get_customer_community(threshold=0.3)
        related = [s for s in similar
                   if s.get("customer_1_id") == customer_id or s.get("customer_2_id") == customer_id][:5]

        # 8. 行业分布
        industry = await get_industry_distribution(customer_name)

        # 组装全景数据
        panoramic = {
            "customer_id": customer_id,
            "customer_name": customer_name,
            "basic_info": {
                "real_name": user["real_name"],
                "phone": user.get("phone", ""),
                "email": user.get("email", ""),
                "balance": float(user.get("balance", 0)),
                "status": user.get("status", "正常"),
                "register_time": user["create_time"].strftime("%Y-%m-%d") if user.get("create_time") else "",
            },
            "risk_info": {
                "risk_level": risk_level or "未评估",
                "risk_score": float(profile["risk_score"]) if profile and profile.get("risk_score") else 0,
                "confidence": float(profile["confidence_score"]) if profile and profile.get("confidence_score") else 0,
                "total_assets": float(profile["total_assets"]) if profile and profile.get("total_assets") else 0,
                "investment_experience": profile.get("investment_experience", "未知") if profile else "未知",
            },
            "holdings": {
                "count": len(holdings),
                "total_value": total_holdings_value,
                "details": holdings[:10],
            },
            "recent_transactions": [
                {
                    "type": tx["transaction_type"],
                    "amount": float(tx.get("amount", 0)),
                    "time": tx["create_time"].strftime("%Y-%m-%d %H:%M") if tx.get("create_time") else "",
                }
                for tx in recent_txs
            ],
            "risk_alerts": [
                {
                    "type": alert["alert_type"],
                    "level": alert["alert_level"],
                    "status": alert["status"],
                    "time": alert["create_time"].strftime("%Y-%m-%d") if alert.get("create_time") else "",
                }
                for alert in alerts
            ],
            "related_customers": related,
            "industry_distribution": industry[:5],
        }

        return {"success": True, "data": panoramic}

    elif tool_name == "query_customer_list":
        limit = arguments.get("limit", 50)
        risk_level = arguments.get("risk_level", "")
        status = arguments.get("status", "")

        # 构建查询条件
        conditions = ["u.user_type = 'CUSTOMER'"]
        params = {"limit": limit}

        if status:
            conditions.append("u.status = :status")
            params["status"] = status

        # 查询客户列表
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            # 基础查询
            base_query = f"""
                SELECT u.id, u.real_name, u.phone, u.email, u.balance, u.status, u.create_time
                FROM sys_user u
                WHERE {' AND '.join(conditions)}
                ORDER BY u.create_time DESC
                LIMIT :limit
            """

            result = await db.execute(text(base_query), params)
            customers = result.mappings().all()

            # 如果有风险等级筛选，需要联表查询
            if risk_level:
                filtered_customers = []
                for c in customers:
                    risk_row = await db.execute(
                        text("SELECT risk_level FROM fin_risk_assessment "
                             "WHERE customer_id = :cid ORDER BY create_time DESC LIMIT 1"),
                        {"cid": c["id"]}
                    )
                    risk = risk_row.mappings().first()
                    if risk and risk["risk_level"] == risk_level:
                        filtered_customers.append(c)
                customers = filtered_customers

        customer_list = []
        for c in customers:
            customer_list.append({
                "id": c["id"],
                "name": c["real_name"],
                "phone": c["phone"],
                "email": c["email"],
                "balance": float(c["balance"] or 0),
                "status": c["status"],
                "register_time": c["create_time"].strftime("%Y-%m-%d") if c["create_time"] else "",
            })

        return {
            "success": True,
            "data": {
                "customers": customer_list,
                "total_count": len(customer_list),
                "limit": limit,
                "filters": {
                    "risk_level": risk_level,
                    "status": status,
                }
            }
        }

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

    # ==================== 审计日志查询结果格式化 ====================

    elif action == "query_audit_log":
        customer_name = data.get("customer_name", "")
        tx_type = data.get("transaction_type", "")
        min_amount = data.get("min_amount", 0)
        days = data.get("query_days", 30)
        transactions = data.get("transactions", [])
        total = data.get("total_count", 0)

        lines = [f"📋 操作审计日志"]
        lines.append(f"• 查询范围: {customer_name} | {tx_type} | 近{days}天")
        if min_amount > 0:
            lines.append(f"• 金额筛选: ≥{min_amount}元")
        lines.append(f"• 查询结果: {total}条记录")

        if not transactions:
            lines.append("\n✅ 未找到符合条件的操作记录")
            return "\n".join(lines)

        # 按类型分组统计
        type_stats = {}
        total_amount = 0
        for tx in transactions:
            t = tx.get("transaction_type", "")
            type_stats[t] = type_stats.get(t, 0) + 1
            total_amount += tx.get("amount", 0)

        lines.append(f"\n📊 统计:")
        type_names = {"purchase": "申购", "redeem": "赎回", "transfer": "转账"}
        for t, count in type_stats.items():
            lines.append(f"  • {type_names.get(t, t)}: {count}笔")
        lines.append(f"  • 总金额: {total_amount:,.2f}元")

        lines.append(f"\n📝 明细（最近{min(len(transactions), 20)}条）:")
        for tx in transactions[:20]:
            t = tx.get("transaction_type", "")
            amount = tx.get("amount", 0)
            product = tx.get("product_name", "")
            time = tx.get("create_time", "")
            operator = tx.get("operator_name", "")
            lines.append(f"  • [{time}] {type_names.get(t, t)} {amount:,.2f}元 "
                        f"| {product or '无产品'} | {operator}")

        if total > 20:
            lines.append(f"  ... 还有 {total - 20} 条记录")

        return "\n".join(lines)

    elif action == "query_customer_panoramic":
        p = data
        lines = [f"📊 客户全景视图 — {p.get('customer_name', '')}（ID: {p.get('customer_id', '')}）"]

        # 基本信息
        basic = p.get("basic_info", {})
        lines.append(f"\n👤 基本信息:")
        lines.append(f"  • 姓名: {basic.get('real_name', '')}")
        lines.append(f"  • 手机: {basic.get('phone', '未填写')}")
        lines.append(f"  • 邮箱: {basic.get('email', '未填写')}")
        lines.append(f"  • 余额: {basic.get('balance', 0):,.2f} 元")
        lines.append(f"  • 状态: {basic.get('status', '正常')}")
        lines.append(f"  • 注册时间: {basic.get('register_time', '未知')}")

        # 风险信息
        risk = p.get("risk_info", {})
        level = risk.get("risk_level", "未评估")
        lines.append(f"\n🛡️ 风险信息:")
        lines.append(f"  • 风险等级: {level}")
        lines.append(f"  • 风险评分: {risk.get('risk_score', 0)}/100")
        lines.append(f"  • 画像置信度: {risk.get('confidence', 0):.2f}")
        lines.append(f"  • 总资产: {risk.get('total_assets', 0):,.2f} 元")
        lines.append(f"  • 投资经验: {risk.get('investment_experience', '未知')}")

        # 持仓信息
        holdings = p.get("holdings", {})
        lines.append(f"\n💼 持仓概况:")
        lines.append(f"  • 持有产品: {holdings.get('count', 0)}只")
        lines.append(f"  • 持仓市值: {holdings.get('total_value', 0):,.2f} 元")
        details = holdings.get("details", [])
        if details:
            for h in details[:5]:
                lines.append(f"  • {h.get('product_name', '')}: {h.get('shares', 0)}份, "
                            f"市值{h.get('current_value', 0)}元, 收益{h.get('profit_ratio', 0)}%")

        # 近期交易
        txs = p.get("recent_transactions", [])
        lines.append(f"\n📝 近期操作（近30天）: {len(txs)}笔")
        type_names = {"purchase": "申购", "redeem": "赎回", "transfer": "转账"}
        for tx in txs[:5]:
            lines.append(f"  • [{tx.get('time', '')}] {type_names.get(tx.get('type', ''), tx.get('type', ''))} "
                        f"{tx.get('amount', 0):,.2f}元")

        # 风控预警
        alerts = p.get("risk_alerts", [])
        if alerts:
            lines.append(f"\n⚠️ 风控预警: {len(alerts)}条")
            level_icons = {"high": "🔴", "medium": "🟡", "low": "🟢"}
            for alert in alerts[:3]:
                lines.append(f"  • [{alert.get('time', '')}] {level_icons.get(alert.get('level', ''), '⚪')} "
                            f"{alert.get('type', '')} | {alert.get('status', '')}")
        else:
            lines.append(f"\n✅ 无风控预警")

        # 关联客户
        related = p.get("related_customers", [])
        if related:
            lines.append(f"\n🔗 关联客户（持仓相似度≥30%）: {len(related)}位")
            for r in related[:3]:
                cid = r.get("customer_1_id") if r.get("customer_2_id") == p.get("customer_id") else r.get("customer_2_id")
                lines.append(f"  • 客户ID {cid}（相似度 {r.get('similarity', 0):.2f}）")

        # 行业分布
        industry = p.get("industry_distribution", [])
        if industry:
            lines.append(f"\n🏭 行业分布:")
            for ind in industry[:5]:
                lines.append(f"  • {ind.get('industry', '')}: {ind.get('percentage', 0)}%")

        return "\n".join(lines)

    elif action == "query_customer_list":
        customers = data.get("customers", [])
        total = data.get("total_count", 0)
        limit = data.get("limit", 50)
        filters = data.get("filters", {})

        lines = [f"👥 客户列表"]
        lines.append(f"• 查询结果: {total}位客户")

        if filters.get("risk_level"):
            lines.append(f"• 风险等级筛选: {filters['risk_level']}")
        if filters.get("status"):
            lines.append(f"• 状态筛选: {filters['status']}")

        if not customers:
            lines.append("\n✅ 未找到符合条件的客户")
            return "\n".join(lines)

        lines.append(f"\n📋 客户明细（显示前{min(total, 20)}位）:")
        for c in customers[:20]:
            status_icon = "✅" if c.get("status") == "正常" else "⚠️"
            lines.append(f"  • {status_icon} {c.get('name', '')} (ID:{c.get('id', '')}) "
                        f"| {c.get('phone', '无')} | 余额{c.get('balance', 0):,.2f}元 "
                        f"| {c.get('status', '')}")

        if total > 20:
            lines.append(f"\n... 还有 {total - 20} 位客户")

        return "\n".join(lines)

    else:
        return f"操作 {action} 执行成功。"
