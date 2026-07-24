"""
业务操作 Agent — NL2API
负责人: LHG
功能: 自然语言 → 意图识别 → 参数提取 → 权限校验 → 执行操作
架构: 工具注册表模式（_TOOL_REGISTRY），支持热注册扩展
校验: P0~P5 全量业务校验（适当性/持仓/余额/风控/反洗钱/审计）
"""

import os
import re
import uuid
import json
import httpx
import logging
from typing import Optional
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from openai import AsyncOpenAI
from sqlalchemy import text

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
    get_customer_community,
    get_industry_distribution,
    resolve_customer_id,
    resolve_product_id,
)
from app.service.event_bus import publish_operation_event
from app.memory.session_memory import SessionMemory
from app.utils.data_masking import mask_text

settings = get_settings()
logger = logging.getLogger(__name__)

# ==================== 业务常量 ====================

_MAX_AMOUNT = 10_000_000          # 单笔上限 1000 万
_DAILY_CUMULATIVE_LIMIT = 2_000_000  # 单日累计上限 200 万（反洗钱）
_DAILY_REDEEM_COUNT_LIMIT = 3     # 单日同一产品赎回次数上限
_LARGE_AMOUNT_NOTE_THRESHOLD = 500_000  # 大额备注阈值（≥50万需填写原因）
_MIN_REMAINING_SHARES = 100       # 赎回后最低保留份额
_MIN_TRANSFER_AMOUNT = 100        # 转账最低金额（元）
_PURCHASE_AMOUNT_MULTIPLE = 100   # 申购金额必须是此值的整数倍
_REDEEM_SHARES_DECIMAL_PLACES = 2 # 赎回份额最大小数位数
_SUSPICIOUS_REPEAT_WINDOW_HOURS = 24  # 可疑交易防重复上报窗口（小时）

# 交易时间窗口
_TRADING_START = time(9, 30)
_TRADING_END = time(15, 0)

# 2026 年法定节假日（非交易日），次年需更新
_HOLIDAYS_2026 = {
    "2026-01-01", "2026-01-02", "2026-01-03",
    "2026-01-26", "2026-01-27", "2026-01-28", "2026-01-29",
    "2026-01-30", "2026-01-31", "2026-02-01",
    "2026-04-04", "2026-04-05", "2026-04-06",
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    "2026-06-19", "2026-06-20", "2026-06-21",
    "2026-09-25", "2026-09-26", "2026-09-27",
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
    "2026-10-05", "2026-10-06", "2026-10-07",
}

# 联系方式正则
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

# 确认消息正则（模块级常量，避免每次调用重复编译）
_CONFIRM_RE = re.compile(
    r"^(?:确认|确定|是的|好的|y|yes)"
    r"(?:\s*(?:[,，:：]?\s*)备注\s*[:：]\s*(?P<note>.+))?$",
    re.IGNORECASE,
)

# 审计日志查询 transaction_type 白名单
_TRANSACTION_TYPE_WHITELIST = {"purchase", "redeem", "transfer_out", "transfer_in"}

# ==================== 适当性匹配矩阵 ====================
# 按设计文档《个人投资者适当性管理指南》§12
_SUITABILITY_MAP = {
    "C1": ["R1", "R2"],
    "C2": ["R1", "R2", "R3"],
    "C3": ["R1", "R2", "R3", "R4"],
    "C4": ["R1", "R2", "R3", "R4", "R5"],
    "C5": ["R1", "R2", "R3", "R4", "R5"],
    "保守型": ["R1", "R2"],
    "稳健型": ["R1", "R2", "R3"],
    "平衡型": ["R1", "R2", "R3", "R4"],
    "进取型": ["R1", "R2", "R3", "R4", "R5"],
    "激进型": ["R1", "R2", "R3", "R4", "R5"],
}

# 豁免规则：C3→R4 / C4→R5 需签署风险揭示书（非阻断警告）
_SUITABILITY_EXEMPTION = {
    "C3": {"R4": "C3平衡型投资者购买R4中高风险产品，须签署《产品风险超越投资者风险承受能力揭示书》，且单只R4产品持仓不超过总资产20%"},
    "C4": {"R5": "C4进取型投资者购买R5高风险产品，须签署《产品风险超越投资者风险承受能力揭示书》，且单只R5产品持仓不超过总资产10%"},
}

_RISK_LEVEL_NORMALIZE = {
    "保守型": "C1", "稳健型": "C2", "平衡型": "C3", "进取型": "C4", "激进型": "C5",
    "R1": "C1", "R2": "C2", "R3": "C3", "R4": "C4", "R5": "C5",
}


def _safe_float(value, field: str = "金额") -> tuple[float, Optional[str]]:
    """安全转换为 float，使用 Decimal 中间层避免精度丢失"""
    try:
        d = Decimal(str(value))
        if d <= 0:
            return 0.0, f"{field}必须大于0"
        if d > _MAX_AMOUNT:
            return 0.0, f"{field}超过上限（{_MAX_AMOUNT}元）"
        return float(d), None
    except (ValueError, TypeError, InvalidOperation):
        return 0.0, f"{field}格式错误（无法转为数字）"


# ==================== LLM 客户端 ====================

_http_client = httpx.AsyncClient(trust_env=False, timeout=settings.llm.openai_timeout)
llm_client = AsyncOpenAI(
    api_key=settings.llm.openai_api_key,
    base_url=settings.llm.openai_base_url,
    timeout=settings.llm.openai_timeout,
    max_retries=3,
    http_client=_http_client,
)

# ==================== 二次确认 Redis 状态管理 ====================

_CONFIRM_PREFIX = "confirm:pending:"
_CONFIRM_TTL = 120


async def _save_pending_confirm(session_id: str, action: str, arguments: dict,
                                 user_id: int, user_role: str,
                                 note_required: bool = False) -> bool:
    """将待确认操作存入 Redis。note_required: 大额(>=50万)是否强制要求备注。"""
    try:
        from app.config.database import get_redis
        r = await get_redis()
        summary = _build_confirmation_summary(action, arguments)
        await r.setex(
            f"{_CONFIRM_PREFIX}{session_id}",
            _CONFIRM_TTL,
            json.dumps({"action": action, "arguments": arguments,
                        "user_id": user_id, "user_role": user_role,
                        "summary": summary, "note_required": note_required}),
        )
        return True
    except Exception:
        return False


async def _load_pending_confirm(session_id: str) -> Optional[dict]:
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
    try:
        from app.config.database import get_redis
        await (await get_redis()).delete(f"{_CONFIRM_PREFIX}{session_id}")
    except Exception:
        pass


def _build_confirmation_summary(action: str, arguments: dict) -> str:
    if action == "purchase_product":
        amount = arguments.get('amount', 0)
        summary = (f"申购：客户 {arguments.get('customer_name','')} "
                   f"购买 {arguments.get('product_name','')}，金额 {amount} 元")
        if amount >= _LARGE_AMOUNT_NOTE_THRESHOLD:
            summary += "\n⚠️ 大额操作，请回复'确认 备注：<原因>'（如：确认 备注：客户主动要求）"
        return summary
    if action == "redeem_product":
        return (f"赎回：客户 {arguments.get('customer_name','')} "
                f"赎回 {arguments.get('product_name','')}，份额 {arguments.get('shares', 0)}")
    if action == "transfer_funds":
        amount = arguments.get('amount', 0)
        summary = (f"转账：{arguments.get('from_customer_name','')} → "
                   f"{arguments.get('to_customer_name','')}，金额 {amount} 元")
        if amount >= _LARGE_AMOUNT_NOTE_THRESHOLD:
            summary += "\n⚠️ 大额操作，请回复'确认 备注：<原因>'（如：确认 备注：内部资金调拨）"
        return summary
    return f"执行 {action}，参数 {arguments}"

# ==================== RBAC 权限矩阵 ====================

RBAC_PERMISSIONS = {
    "理财顾问": ["purchase_product", "redeem_product", "transfer_funds", "redo_assessment",
                "query_product", "query_product_list", "get_customer_holdings", "get_suitable_products",
                "query_audit_log", "query_customer_panoramic", "query_customer_list"],
    "客户经理": ["update_contact", "create_work_order", "query_product", "query_product_list",
                "get_customer_holdings", "query_audit_log", "query_customer_panoramic", "query_customer_list"],
    "风控专员": ["report_suspicious", "query_product", "query_product_list",
                "query_audit_log", "query_customer_panoramic", "query_customer_list"],
    "管理员": ["purchase_product", "redeem_product", "transfer_funds", "redo_assessment", "update_contact",
              "query_product", "query_product_list", "get_customer_holdings", "get_suitable_products",
              "report_suspicious", "create_work_order",
              "query_audit_log", "query_customer_panoramic", "query_customer_list"],
}

CONFIRM_THRESHOLDS = {
    "purchase_product": 10000,
    "redeem_product": 10000,
    "transfer_funds": 50000,
}

# ==================== Function Calling Tool 定义 ====================

TOOLS = [
    {"type": "function", "function": {"name": "purchase_product",
        "description": "帮客户申购基金产品。需要指定客户姓名、产品名称和申购金额",
        "parameters": {"type": "object", "properties": {
            "customer_name": {"type": "string", "description": "客户姓名"},
            "product_name": {"type": "string", "description": "产品名称"},
            "amount": {"type": "number", "description": "申购金额（元）"},
        }, "required": ["customer_name", "product_name", "amount"]}}},
    {"type": "function", "function": {"name": "redeem_product",
        "description": "帮客户赎回基金产品。需要指定客户姓名、产品名称和赎回份额",
        "parameters": {"type": "object", "properties": {
            "customer_name": {"type": "string", "description": "客户姓名"},
            "product_name": {"type": "string", "description": "产品名称"},
            "shares": {"type": "number", "description": "赎回份额"},
        }, "required": ["customer_name", "product_name", "shares"]}}},
    {"type": "function", "function": {"name": "transfer_funds",
        "description": "帮客户转账。需要指定转出客户、转入客户和金额",
        "parameters": {"type": "object", "properties": {
            "from_customer_name": {"type": "string", "description": "转出客户姓名"},
            "to_customer_name": {"type": "string", "description": "转入客户姓名"},
            "amount": {"type": "number", "description": "转账金额（元）"},
        }, "required": ["from_customer_name", "to_customer_name", "amount"]}}},
    {"type": "function", "function": {"name": "redo_assessment",
        "description": "给客户重新做风险评估。需要传入客户在各评分题上的作答（整数列表），如未提供答案请先询问客户完成问卷",
        "parameters": {"type": "object", "properties": {
            "customer_name": {"type": "string", "description": "客户姓名"},
            "answers": {"type": "array", "items": {"type": "integer"},
                        "description": "客户在各评分题上的作答（整数列表，每题1-20分）"},
        }, "required": ["customer_name", "answers"]}}},
    {"type": "function", "function": {"name": "update_contact",
        "description": "更新客户的联系信息（手机号、邮箱等）",
        "parameters": {"type": "object", "properties": {
            "customer_name": {"type": "string", "description": "客户姓名"},
            "field": {"type": "string", "description": "字段名: phone/email"},
            "value": {"type": "string", "description": "新值"},
        }, "required": ["customer_name", "field", "value"]}}},
    {"type": "function", "function": {"name": "query_product",
        "description": "查询某只基金的详细信息",
        "parameters": {"type": "object", "properties": {
            "product_name": {"type": "string", "description": "产品名称"},
        }, "required": ["product_name"]}}},
    {"type": "function", "function": {"name": "query_product_list",
        "description": "查询在售产品列表",
        "parameters": {"type": "object", "properties": {
            "risk_level": {"type": "string", "description": "风险等级 R1-R5，可选"},
        }}}},
    {"type": "function", "function": {"name": "get_customer_holdings",
        "description": "查询客户当前持仓",
        "parameters": {"type": "object", "properties": {
            "customer_name": {"type": "string", "description": "客户姓名"},
        }, "required": ["customer_name"]}}},
    {"type": "function", "function": {"name": "get_suitable_products",
        "description": "根据风险等级查询适当性匹配的产品",
        "parameters": {"type": "object", "properties": {
            "risk_level": {"type": "string", "description": "风险等级 R1-R5"},
        }, "required": ["risk_level"]}}},
    {"type": "function", "function": {"name": "report_suspicious",
        "description": "上报客户可疑交易",
        "parameters": {"type": "object", "properties": {
            "customer_name": {"type": "string", "description": "客户姓名"},
            "reason": {"type": "string", "description": "可疑原因"},
        }, "required": ["customer_name", "reason"]}}},
    {"type": "function", "function": {"name": "create_work_order",
        "description": "为客户创建业务工单",
        "parameters": {"type": "object", "properties": {
            "customer_name": {"type": "string", "description": "客户姓名"},
            "order_type": {"type": "string", "description": "工单类型: 投诉/建议/咨询"},
            "content": {"type": "string", "description": "工单内容"},
        }, "required": ["customer_name", "content"]}}},
    {"type": "function", "function": {"name": "query_audit_log",
        "description": "查询客户操作审计日志（申购/赎回/转账记录）。用于内部审计和合规检查",
        "parameters": {"type": "object", "properties": {
            "customer_name": {"type": "string", "description": "客户姓名（可选）"},
            "transaction_type": {"type": "string", "description": "操作类型：purchase/redeem/transfer_out/transfer_in（可选）"},
            "min_amount": {"type": "number", "description": "最小金额（可选）"},
            "days": {"type": "integer", "description": "查询天数范围，默认30天"},
        }}}},
    {"type": "function", "function": {"name": "query_customer_panoramic",
        "description": "查询客户全景视图（一站式展示客户基本信息、持仓、近期操作、风险标记）",
        "parameters": {"type": "object", "properties": {
            "customer_name": {"type": "string", "description": "客户姓名"},
        }, "required": ["customer_name"]}}},
    {"type": "function", "function": {"name": "query_customer_list",
        "description": "查询系统中的客户列表",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "返回数量限制，默认50"},
            "risk_level": {"type": "string", "description": "按风险等级筛选：C1/C2/C3/C4/C5（可选）"},
            "status": {"type": "string", "description": "按状态筛选：正常/冻结（可选）"},
        }}}},
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
- query_audit_log: 查询客户操作审计日志
- query_customer_panoramic: 查询客户全景视图
- query_customer_list: 查询系统中的客户列表

客户识别规则（重要！）：
- "演示客户05"、"演示客户5" -> customer_name 填 "演示客户05"
- "客户ID 5"、"客户ID：5"、"客户5" -> customer_name 填 "客户ID 5"
- 如果用户用纯数字ID指定客户，请用"客户ID N"格式

回复风格：简洁、结构化、专业。使用 emoji 标记操作状态
"""


def check_permission(user_role: str, action: str) -> bool:
    allowed = RBAC_PERMISSIONS.get(user_role, [])
    return action in allowed


def needs_confirmation(action: str, amount: float = 0) -> bool:
    if action not in CONFIRM_THRESHOLDS:
        return False
    return amount > CONFIRM_THRESHOLDS[action]


# ==================================================================
# 业务校验函数（P0~P5）
# ==================================================================

async def _get_customer_risk_level(customer_id: int, db) -> Optional[str]:
    try:
        row = await db.execute(
            text("SELECT risk_level FROM fin_risk_assessment WHERE customer_id = :cid "
                 "ORDER BY create_time DESC LIMIT 1"), {"cid": customer_id})
        row = row.mappings().first()
        if not row:
            return None
        return _RISK_LEVEL_NORMALIZE.get(row["risk_level"], row["risk_level"])
    except Exception:
        return None


async def _get_product_risk_level(product_id: int, db) -> Optional[str]:
    try:
        row = await db.execute(
            text("SELECT risk_level FROM fin_product WHERE id = :pid"), {"pid": product_id})
        row = row.mappings().first()
        return row["risk_level"] if row else None
    except Exception:
        return None


async def _check_suitability_combined(customer_id: int, product_id: int, db) -> tuple[Optional[str], Optional[str]]:
    """适当性校验（合并版）：返回 (block_error, exemption_warning)"""
    customer_level = await _get_customer_risk_level(customer_id, db)
    if not customer_level:
        return "客户尚未完成风险评估，请先完成风评", None
    product_level = await _get_product_risk_level(product_id, db)
    if not product_level:
        return None, None
    allowed_levels = _SUITABILITY_MAP.get(customer_level, [])
    if product_level not in allowed_levels:
        return (f"⚠️ 适当性不匹配：客户风险等级 {customer_level}，"
                f"产品风险等级 {product_level}，"
                f"允许购买 {', '.join(allowed_levels)} 级别产品"), None
    exemption_rules = _SUITABILITY_EXEMPTION.get(customer_level, {})
    warning_text = exemption_rules.get(product_level)
    if warning_text:
        return None, f"⚠️ 豁免购买提示：{warning_text}"
    return None, None


async def _check_product_status(product_id: int, operation: str, db) -> Optional[str]:
    _PURCHASE_ALLOWED = {"在售", "on_sale"}
    _PURCHASE_BLOCKED = {
        "已下架": "已下架", "off_sale": "已下架",
        "暂停申购": "暂停申购", "suspended": "暂停申购",
        "已结清": "已结清", "ended": "已结清",
    }
    _REDEEM_BLOCKED = {
        "已终止": "已终止", "terminated": "已终止",
        "清算中": "清算中", "liquidating": "清算中",
    }
    try:
        row = await db.execute(
            text("SELECT status, product_name FROM fin_product WHERE id = :pid"), {"pid": product_id})
        row = row.mappings().first()
        if not row:
            return None
        status = row["status"]
        product_name = row.get("product_name", "")
        if operation == "purchase" and status not in _PURCHASE_ALLOWED:
            return f"产品【{product_name}】当前状态为【{_PURCHASE_BLOCKED.get(status, status)}】，无法申购"
        if operation == "redeem" and status in _REDEEM_BLOCKED:
            return f"产品【{product_name}】当前状态为【{_REDEEM_BLOCKED[status]}】，无法赎回"
    except Exception as e:
        return f"产品状态查询失败: {e}"
    return None


async def _check_customer_status(customer_id: int, db) -> Optional[str]:
    try:
        row = await db.execute(
            text("SELECT status FROM sys_user WHERE id = :id"), {"id": customer_id})
        row = row.mappings().first()
        if not row:
            return "未找到客户账户"
        if row["status"] != "正常":
            return f"客户账户状态异常：{row['status']}，无法执行操作"
    except Exception as e:
        return f"客户状态查询失败: {e}"
    return None


async def _check_holdings(customer_id: int, product_id: int, shares: float, db) -> Optional[str]:
    try:
        row = await db.execute(
            text("SELECT shares FROM fin_holdings "
                 "WHERE customer_id = :cid AND product_id = :pid AND status = '持有中'"),
            {"cid": customer_id, "pid": product_id})
        row = row.mappings().first()
        if not row:
            return "客户未持有该产品，无法赎回"
        holding = Decimal(str(row["shares"] or 0))
        if Decimal(str(shares)) > holding:
            return f"赎回份额({shares})超过持有份额({holding})"
    except Exception as e:
        return f"持仓查询失败: {e}"
    return None


async def _check_balance(customer_id: int, amount: float, db) -> Optional[str]:
    try:
        row = await db.execute(
            text("SELECT balance FROM sys_user WHERE id = :id"), {"id": customer_id})
        row = row.mappings().first()
        if not row:
            return "未找到客户账户"
        balance = Decimal(str(row["balance"] or 0))
        if Decimal(str(amount)) > balance:
            return f"转出方余额不足：余额{balance}元，转账{amount}元"
    except Exception as e:
        return f"余额查询失败: {e}"
    return None


async def _check_risk_assessment_validity(customer_id: int, db) -> Optional[str]:
    try:
        row = await db.execute(
            text("SELECT risk_level, valid_until FROM fin_risk_assessment "
                 "WHERE customer_id = :cid ORDER BY create_time DESC LIMIT 1"),
            {"cid": customer_id})
        row = row.mappings().first()
        if not row:
            return "客户尚未完成风险评估，请先完成风评"
        valid_until = row.get("valid_until")
        if valid_until:
            expiry_date = valid_until.date() if callable(getattr(valid_until, 'date', None)) else valid_until
            if hasattr(expiry_date, 'date'):
                expiry_date = expiry_date.date()
            if expiry_date < datetime.now().date():
                return f"⚠️ 客户风险评估已过期（有效期至 {expiry_date}），请重新完成风险评估后再操作"
    except Exception as e:
        return f"风评有效期查询失败: {e}"
    return None


def _check_trading_hours() -> Optional[str]:
    now = datetime.now()
    if now.strftime("%Y-%m-%d") in _HOLIDAYS_2026:
        return "⚠️ 当前为法定节假日非交易日，操作将顺延至下一交易日处理"
    if now.weekday() >= 5:
        return "⚠️ 当前为周末非交易日，操作将顺延至下一交易日处理"
    current_time = now.time()
    if current_time < _TRADING_START or current_time > _TRADING_END:
        return "⚠️ 当前非交易时间（交易时间 9:30-15:00），操作将顺延至下一交易日处理"
    return None


async def _check_daily_cumulative(customer_id: int, amount: float, db) -> Optional[str]:
    """单日累计限额：排除 transfer_in（收入不占流出额度）"""
    try:
        today = datetime.now().date()
        row = await db.execute(text("""
            SELECT COALESCE(SUM(amount), 0) AS total FROM fin_transaction
            WHERE customer_id = :cid AND DATE(create_time) = :today
              AND status IN ('已确认', '待确认')
              AND transaction_type NOT IN ('transfer_in')
        """), {"cid": customer_id, "today": today})
        row = row.mappings().first()
        daily_total = float(row["total"]) if row else 0
        if daily_total + amount > _DAILY_CUMULATIVE_LIMIT:
            return (f"⚠️ 超出单日累计限额：今日已交易 {daily_total:,.2f} 元，"
                    f"本次 {amount:,.2f} 元，累计将超过限额 {_DAILY_CUMULATIVE_LIMIT:,.0f} 元")
    except Exception as e:
        return f"单日累计限额查询失败: {e}"
    return None


def _check_self_transfer(from_id: int, to_id: int) -> Optional[str]:
    if from_id == to_id:
        return "⚠️ 转出方和转入方不能是同一客户"
    return None


async def _check_risk_flag(customer_id: int, db, label: str = "客户") -> Optional[str]:
    try:
        row = await db.execute(
            text("SELECT risk_flag FROM fin_customer_profile WHERE customer_id = :cid"),
            {"cid": customer_id})
        row = row.mappings().first()
        if not row:
            return None
        risk_flag = row.get("risk_flag", "normal")
        if risk_flag == "high":
            return f"⚠️ {label}被标记为【高风险】，请确认是否继续操作"
        elif risk_flag == "warning":
            return f"⚠️ {label}存在【风险预警】，请注意核实"
    except Exception:
        pass
    return None


async def _check_pending_risk_alerts(customer_id: int, db, label: str = "客户") -> Optional[str]:
    try:
        row = await db.execute(text("""
            SELECT COUNT(*) AS cnt, MAX(alert_level) AS max_level FROM fin_risk_alert
            WHERE customer_id = :cid AND status = 'pending'
              AND create_time >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        """), {"cid": customer_id})
        row = row.mappings().first()
        if not row:
            return None
        cnt = int(row["cnt"])
        max_level = row.get("max_level", "")
        if cnt > 0:
            icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(max_level, "⚪")
            return f"{icon} {label}近30天有 {cnt} 条待处理风控预警（最高级别: {max_level}）"
    except Exception:
        pass
    return None


async def _check_daily_redeem_count(customer_id: int, product_id: int, db) -> Optional[str]:
    try:
        today = datetime.now().date()
        row = await db.execute(text("""
            SELECT COUNT(*) AS cnt FROM fin_transaction
            WHERE customer_id = :cid AND product_id = :pid
              AND transaction_type = 'redeem' AND DATE(create_time) = :today
              AND status IN ('已确认', '待确认')
        """), {"cid": customer_id, "pid": product_id, "today": today})
        row = row.mappings().first()
        cnt = int(row["cnt"]) if row else 0
        if cnt >= _DAILY_REDEEM_COUNT_LIMIT:
            return f"⚠️ 该产品今日已赎回 {cnt} 次，达到单日上限（{_DAILY_REDEEM_COUNT_LIMIT}次），请明日再操作"
    except Exception as e:
        return f"赎回次数查询失败: {e}"
    return None


def _check_contact_format(field: str, value: str) -> Optional[str]:
    if not value or not value.strip():
        return "联系方式不能为空"
    value = value.strip()
    if field == "phone" and not _PHONE_RE.match(value):
        return f"手机号格式错误：{value}，应为11位大陆手机号"
    if field == "email" and not _EMAIL_RE.match(value):
        return f"邮箱格式错误：{value}"
    return None


async def _check_transfer_eligibility(to_id: int, db) -> Optional[str]:
    try:
        row = await db.execute(
            text("SELECT status FROM sys_user WHERE id = :id"), {"id": to_id})
        row = row.mappings().first()
        if not row:
            return "转入方账户不存在"
        if row["status"] == "注销":
            return "转入方账户已注销，无法接收转账"
        if row["status"] == "冻结":
            return "转入方账户已冻结，无法正常接收转账"
    except Exception as e:
        return f"转入方资格查询失败: {e}"
    return None


async def _check_min_remaining_shares(customer_id: int, product_id: int,
                                       redeem_shares: float, db) -> Optional[str]:
    try:
        row = await db.execute(
            text("SELECT shares FROM fin_holdings "
                 "WHERE customer_id = :cid AND product_id = :pid AND status = '持有中'"),
            {"cid": customer_id, "pid": product_id})
        row = row.mappings().first()
        if not row:
            return None
        holding = Decimal(str(row["shares"] or 0))
        remaining = holding - Decimal(str(redeem_shares))
        if remaining > 0 and remaining < Decimal(str(_MIN_REMAINING_SHARES)):
            return (f"⚠️ 赎回后剩余份额 {remaining} 份，低于最低持有要求 {_MIN_REMAINING_SHARES} 份。"
                    f"请全部赎回（{holding} 份）或减少赎回份额")
    except Exception as e:
        return f"最低保留份额校验失败: {e}"
    return None


def _check_purchase_amount_multiple(amount: float) -> Optional[str]:
    if amount <= 0:
        return None
    if Decimal(str(amount)) % Decimal(str(_PURCHASE_AMOUNT_MULTIPLE)) != 0:
        return f"🚫 申购金额必须为 {_PURCHASE_AMOUNT_MULTIPLE} 元的整数倍，当前金额 {amount} 元"
    return None


def _check_min_transfer_amount(amount: float) -> Optional[str]:
    if amount < _MIN_TRANSFER_AMOUNT:
        return f"🚫 转账金额不得低于 {_MIN_TRANSFER_AMOUNT} 元，当前金额 {amount} 元"
    return None


async def _check_product_min_purchase_amount(product_id: int, amount: float, db) -> Optional[str]:
    try:
        row = await db.execute(
            text("SELECT min_purchase_amount, product_name FROM fin_product WHERE id = :pid"),
            {"pid": product_id})
        row = row.mappings().first()
        if not row or row.get("min_purchase_amount") is None:
            return None
        if Decimal(str(amount)) < Decimal(str(row["min_purchase_amount"])):
            return f"🚫 产品【{row.get('product_name', '')}】最低起购金额为 {row['min_purchase_amount']} 元"
    except Exception as e:
        if "unknown column" in str(e).lower():
            return None
        return f"产品起购金额查询失败: {e}"
    return None


async def _check_product_raise_quota(product_id: int, amount: float, db) -> Optional[str]:
    try:
        row = await db.execute(
            text("SELECT max_raise_amount, raised_amount, product_name FROM fin_product WHERE id = :pid"),
            {"pid": product_id})
        row = row.mappings().first()
        if not row:
            return None
        max_raise = row.get("max_raise_amount")
        if not max_raise or max_raise == 0:
            return None
        raised = Decimal(str(row.get("raised_amount") or 0))
        quota = Decimal(str(max_raise)) - raised
        if quota < Decimal(str(amount)):
            return f"🚫 产品【{row.get('product_name', '')}】募集额度不足：剩余额度 {quota} 元"
    except Exception as e:
        if "unknown column" in str(e).lower():
            return None
        return f"产品额度查询失败: {e}"
    return None


def _check_redeem_shares_precision(shares: float) -> Optional[str]:
    if shares <= 0:
        return None
    dp = abs(Decimal(str(shares)).as_tuple().exponent)
    if dp > _REDEEM_SHARES_DECIMAL_PLACES:
        return f"🚫 赎回份额最多保留 {_REDEEM_SHARES_DECIMAL_PLACES} 位小数，当前 {shares} 位精度过高"
    return None


async def _check_suspicious_repeat(customer_id: int, reason: str, db) -> Optional[str]:
    try:
        row = await db.execute(text("""
            SELECT reason, create_time FROM fin_suspicious_report
            WHERE customer_id = :cid
              AND create_time >= DATE_SUB(NOW(), INTERVAL :hours HOUR)
            ORDER BY create_time DESC LIMIT 5
        """), {"cid": customer_id, "hours": _SUSPICIOUS_REPEAT_WINDOW_HOURS})
        for r in row.mappings().all():
            if r.get("reason", "").strip() == reason.strip():
                t = r.get("create_time")
                ts = t.strftime("%m-%d %H:%M") if t else "近期"
                return f"⚠️ 该客户于 {ts} 已上报过相同原因，请确认是否需要重复上报"
    except Exception:
        pass
    return None


# ==================== 审计工单自动创建 ====================

_AUDIT_OPS = {"purchase_product", "redeem_product", "transfer_funds"}


async def _create_audit_work_order(action: str, arguments: dict, data: dict,
                                    operator_id: int) -> None:
    if action not in _AUDIT_OPS:
        return
    try:
        from app.config.database import async_session_factory
        customer_id = arguments.get("customer_id") or arguments.get("customer_name", "")
        if isinstance(customer_id, str):
            cid = await resolve_customer_id(customer_id)
            if not cid:
                return
            customer_id = cid

        if action == "purchase_product":
            detail = f"申购：产品 {arguments.get('product_name', '')}，金额 {arguments.get('amount', 0)} 元"
        elif action == "redeem_product":
            detail = f"赎回：产品 {arguments.get('product_name', '')}，份额 {arguments.get('shares', 0)}"
        elif action == "transfer_funds":
            detail = (f"转账：{arguments.get('from_customer_name', '')} -> "
                      f"{arguments.get('to_customer_name', '')}，金额 {arguments.get('amount', 0)} 元")
        else:
            detail = f"操作 {action}"

        txn_no = (data or {}).get("transaction_no", "")
        if txn_no:
            detail += f"，流水号 {txn_no}"
        note = arguments.get("operator_note", "")
        if note:
            detail += f"，操作员备注：{note}"

        wo_no = f"AUD{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
        biz_json = json.dumps({
            "action": action, "detail": detail,
            "arguments": {k: v for k, v in arguments.items() if k != "operator_note"},
            "result": {"transaction_no": txn_no}, "auto_created": True,
        }, ensure_ascii=False)

        async with async_session_factory() as db:
            await db.execute(text("""
                INSERT INTO biz_work_order
                (work_order_no, order_type, customer_id, submitter_id,
                 status, current_node, remark, biz_content, create_time)
                VALUES (:n, '操作审计', :c, :s, '已完成', '系统自动', :r, :b, NOW())
            """), {"n": wo_no, "c": customer_id, "s": operator_id,
                   "r": detail[:255], "b": biz_json})
            await db.commit()
        logger.info("审计工单已创建: %s | action=%s | customer=%s", wo_no, action, customer_id)
    except Exception as e:
        logger.warning("审计工单创建失败（不影响主流程）: %s", e)


# ==================== 记忆归档 ====================

async def _archive_memory(memory: "SessionMemory", user_id: int) -> None:
    try:
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            await memory.archive(db, user_id, agent_type="operator")
    except Exception:
        pass


async def _recall_recent_operations(user_id: int) -> str:
    if not user_id:
        return ""
    try:
        from app.config.database import async_session_factory
        async with async_session_factory() as db:
            result = await db.execute(text("""
                SELECT content, create_time FROM conversation_archive
                WHERE user_id = :uid AND agent_type = 'operator' AND role = 'assistant'
                  AND (content LIKE '%%✅%%' OR content LIKE '%%操作%%' OR content LIKE '%%成功%%')
                ORDER BY create_time DESC LIMIT 10
            """), {"uid": user_id})
            rows = result.mappings().all()
        if not rows:
            return ""
        summaries = []
        for row in rows:
            content = row["content"] or ""
            ts = row["create_time"].strftime("%m-%d %H:%M") if row.get("create_time") else ""
            first_line = content.split("\n")[0][:80]
            if first_line:
                summaries.append(f"[{ts}] {first_line}")
        return "近期操作:\n" + "\n".join(summaries[:5]) if summaries else ""
    except Exception:
        return ""


# ==================================================================
# 工具处理函数（注册表模式）
# ==================================================================

async def _resolve_customer(arguments: dict, key: str = "customer_name") -> tuple[int | None, str | None]:
    name = arguments.get(key, "")
    if not name:
        return None, f"缺少参数: {key}"
    cid = await resolve_customer_id(name)
    if not cid:
        return None, f"未找到客户: {name}"
    return cid, None


async def _resolve_product(arguments: dict) -> tuple[int | None, str | None]:
    name = arguments.get("product_name", "")
    if not name:
        return None, "缺少参数: product_name"
    pid = await resolve_product_id(name)
    if not pid:
        return None, f"未找到产品: {name}"
    return pid, None


# ---------- 申购 ----------

async def _tool_purchase(arguments: dict, operator_id: int | None) -> dict:
    if not operator_id:
        return {"success": False, "message": "系统异常：操作员身份未识别，请重新登录后再试"}

    cid, err = await _resolve_customer(arguments)
    if err:
        return {"success": False, "message": err}
    pid, err = await _resolve_product(arguments)
    if err:
        return {"success": False, "message": err}
    amount, err = _safe_float(arguments.get("amount", 0), "申购金额")
    if err:
        return {"success": False, "message": err}

    from app.config.database import async_session_factory
    async with async_session_factory() as db:
        if e := _check_purchase_amount_multiple(amount):
            return {"success": False, "message": e}
        if e := await _check_product_min_purchase_amount(pid, amount, db):
            return {"success": False, "message": e}
        if e := await _check_product_raise_quota(pid, amount, db):
            return {"success": False, "message": e}
        if e := await _check_product_status(pid, "purchase", db):
            return {"success": False, "message": e}
        if e := await _check_customer_status(cid, db):
            return {"success": False, "message": e}
        suit_err, exemption_warn = await _check_suitability_combined(cid, pid, db)
        if suit_err:
            return {"success": False, "message": suit_err}
        if e := await _check_risk_assessment_validity(cid, db):
            return {"success": False, "message": e}
        if e := await _check_daily_cumulative(cid, amount, db):
            return {"success": False, "message": e}
        risk_warnings = []
        if exemption_warn:
            risk_warnings.append(exemption_warn)
        if w := await _check_risk_flag(cid, db, "客户"):
            risk_warnings.append(w)
        if w := await _check_pending_risk_alerts(cid, db, "客户"):
            risk_warnings.append(w)

    trading_warn = _check_trading_hours()

    from app.config.database import async_session_factory
    async with async_session_factory() as db:
        result = await purchase_product(
            body={"customer_id": cid, "product_id": pid, "amount": amount, "operator_id": operator_id}, db=db)
        msg = result.message
        if result.code == 200 and trading_warn:
            msg = f"{msg}（{trading_warn}）"
        if result.code == 200 and risk_warnings:
            msg = f"{msg}\n\n⚠️ 风控提示:\n" + "\n".join(risk_warnings)
        return {"success": result.code == 200, "message": msg, "data": result.data}


# ---------- 赎回 ----------

async def _tool_redeem(arguments: dict, operator_id: int | None) -> dict:
    if not operator_id:
        return {"success": False, "message": "系统异常：操作员身份未识别，请重新登录后再试"}

    cid, err = await _resolve_customer(arguments)
    if err:
        return {"success": False, "message": err}
    pid, err = await _resolve_product(arguments)
    if err:
        return {"success": False, "message": err}
    shares, err = _safe_float(arguments.get("shares", 0), "赎回份额")
    if err:
        return {"success": False, "message": err}
    if e := _check_redeem_shares_precision(shares):
        return {"success": False, "message": e}

    trading_warn = _check_trading_hours()

    from app.config.database import async_session_factory
    async with async_session_factory() as db:
        if e := await _check_product_status(pid, "redeem", db):
            return {"success": False, "message": e}
        if e := await _check_customer_status(cid, db):
            return {"success": False, "message": e}
        if e := await _check_holdings(cid, pid, shares, db):
            return {"success": False, "message": e}
        if e := await _check_daily_redeem_count(cid, pid, db):
            return {"success": False, "message": e}
        # 赎回纳入单日累计（估算金额，NULL 安全）
        hrow = await db.execute(
            text("SELECT shares, current_value, cost_amount FROM fin_holdings "
                 "WHERE customer_id = :cid AND product_id = :pid AND status = '持有中'"),
            {"cid": cid, "pid": pid})
        h = hrow.mappings().first()
        if h and h["shares"] and h["shares"] > 0:
            raw_val = h["current_value"]
            if raw_val is None or float(raw_val) <= 0:
                raw_val = h.get("cost_amount") or 0
            est_amount = shares * (float(raw_val) / float(h["shares"]))
            if e := await _check_daily_cumulative(cid, est_amount, db):
                return {"success": False, "message": e}
        min_shares_warn = await _check_min_remaining_shares(cid, pid, shares, db)
        risk_warnings = []
        if w := await _check_risk_flag(cid, db, "客户"):
            risk_warnings.append(w)
        if w := await _check_pending_risk_alerts(cid, db, "客户"):
            risk_warnings.append(w)

    from app.config.database import async_session_factory
    async with async_session_factory() as db:
        result = await redeem_product(body={
            "customer_id": cid, "product_id": pid, "shares": shares, "operator_id": operator_id,
        }, db=db)
        msg = result.message
        if result.code == 200 and trading_warn:
            msg = f"{msg}（{trading_warn}）"
        if result.code == 200 and min_shares_warn:
            msg = f"{msg}\n\n{min_shares_warn}"
        if result.code == 200 and risk_warnings:
            msg = f"{msg}\n\n⚠️ 风控提示:\n" + "\n".join(risk_warnings)
        return {"success": result.code == 200, "message": msg, "data": result.data}


# ---------- 转账 ----------

async def _tool_transfer(arguments: dict, operator_id: int | None) -> dict:
    if not operator_id:
        return {"success": False, "message": "系统异常：操作员身份未识别，请重新登录后再试"}

    from_id, err = await _resolve_customer(arguments, "from_customer_name")
    if err:
        return {"success": False, "message": err}
    to_id, err = await _resolve_customer(arguments, "to_customer_name")
    if err:
        return {"success": False, "message": err}
    amount, err = _safe_float(arguments.get("amount", 0), "转账金额")
    if err:
        return {"success": False, "message": err}
    if e := _check_min_transfer_amount(amount):
        return {"success": False, "message": e}
    if e := _check_self_transfer(from_id, to_id):
        return {"success": False, "message": e}

    trading_warn = _check_trading_hours()

    from app.config.database import async_session_factory
    async with async_session_factory() as db:
        if e := await _check_customer_status(from_id, db):
            return {"success": False, "message": f"转出方{e}"}
        if e := await _check_balance(from_id, amount, db):
            return {"success": False, "message": e}
        if e := await _check_transfer_eligibility(to_id, db):
            return {"success": False, "message": e}
        if e := await _check_daily_cumulative(from_id, amount, db):
            return {"success": False, "message": e}
        risk_warnings = []
        for sid, label in [(from_id, "转出方"), (to_id, "转入方")]:
            if w := await _check_risk_flag(sid, db, label):
                risk_warnings.append(w)
            if w := await _check_pending_risk_alerts(sid, db, label):
                risk_warnings.append(w)

    from app.config.database import async_session_factory
    async with async_session_factory() as db:
        result = await transfer_funds(body={
            "from_customer_id": from_id, "to_customer_id": to_id,
            "amount": amount, "operator_id": operator_id,
        }, db=db)
        msg = result.message
        if result.code == 200 and trading_warn:
            msg = f"{msg}（{trading_warn}）"
        if result.code == 200 and risk_warnings:
            msg = f"{msg}\n\n⚠️ 风控提示:\n" + "\n".join(risk_warnings)
        return {"success": result.code == 200, "message": msg, "data": result.data}


# ---------- 风评重做 ----------

async def _tool_redo_assessment(arguments: dict, operator_id: int | None) -> dict:
    if not operator_id:
        return {"success": False, "message": "系统异常：操作员身份未识别，请重新登录后再试"}

    cid, err = await _resolve_customer(arguments)
    if err:
        return {"success": False, "message": err}
    answers = arguments.get("answers", [])
    if not answers:
        return {"success": False, "message": "请先让客户完成风险评估问卷，获取答案后再执行风评重做"}
    if not isinstance(answers, list):
        return {"success": False, "message": "answers 必须为列表"}
    for i, ans in enumerate(answers):
        try:
            v = int(ans)
            if v < 1 or v > 20:
                return {"success": False, "message": f"第{i+1}题答案 {ans} 超出范围（应为 1-20）"}
        except (ValueError, TypeError):
            return {"success": False, "message": f"第{i+1}题答案 {ans} 格式错误（应为整数）"}

    from app.config.database import async_session_factory
    async with async_session_factory() as db:
        if e := await _check_customer_status(cid, db):
            return {"success": False, "message": e}
        recent_row = await db.execute(text(
            "SELECT create_time FROM fin_risk_assessment WHERE customer_id = :cid "
            "AND create_time >= DATE_SUB(NOW(), INTERVAL 1 DAY) ORDER BY create_time DESC LIMIT 1"),
            {"cid": cid})
        recent = recent_row.mappings().first()

    from app.config.database import async_session_factory
    async with async_session_factory() as db:
        result = await redo_assessment(body={
            "customer_id": cid, "answers": answers, "operator_id": operator_id,
        }, db=db)
        msg = result.message
        if result.code == 200 and recent:
            lt = recent["create_time"].strftime("%Y-%m-%d %H:%M") if recent.get("create_time") else "近期"
            msg = f"{msg}\n\n⚠️ 提示：该客户于 {lt} 刚完成过风评，请确认是否需要重做"
        return {"success": result.code == 200, "message": msg, "data": result.data}


# ---------- 联系方式更新 ----------

async def _tool_update_contact(arguments: dict, _operator_id: int | None) -> dict:
    cid, err = await _resolve_customer(arguments)
    if err:
        return {"success": False, "message": err}
    field = arguments.get("field", "")
    value = arguments.get("value", "")
    if e := _check_contact_format(field, value):
        return {"success": False, "message": e}
    if len(value.strip()) > 128:
        return {"success": False, "message": "联系方式长度超限（最大128字符）"}

    from app.config.database import async_session_factory
    async with async_session_factory() as db:
        if e := await _check_customer_status(cid, db):
            return {"success": False, "message": e}
        result = await update_contact(body={"customer_id": cid, "field": field, "value": value}, db=db)
        return {"success": result.code == 200, "message": result.message, "data": result.data}


# ---------- 可疑交易上报 ----------

async def _tool_report_suspicious(arguments: dict, operator_id: int | None) -> dict:
    if not operator_id:
        return {"success": False, "message": "系统异常：操作员身份未识别，请重新登录后再试"}

    cid, err = await _resolve_customer(arguments)
    if err:
        return {"success": False, "message": err}
    reason = arguments.get("reason", "")
    if not reason or not reason.strip():
        return {"success": False, "message": "可疑交易上报原因不能为空"}
    if len(reason) > 2000:
        return {"success": False, "message": "上报原因长度超限（最大2000字符）"}

    from app.config.database import async_session_factory
    async with async_session_factory() as db:
        repeat_warn = await _check_suspicious_repeat(cid, reason, db)
        if e := await _check_customer_status(cid, db):
            return {"success": False, "message": e}
        result = await report_suspicious(body={
            "customer_id": cid, "reason": reason, "reporter_id": operator_id,
        }, db=db)
        msg = result.message
        if result.code == 200 and repeat_warn:
            msg = f"{msg}\n\n{repeat_warn}"
        return {"success": result.code == 200, "message": msg, "data": result.data}


# ---------- 创建工单 ----------

async def _tool_create_work_order(arguments: dict, operator_id: int | None) -> dict:
    if not operator_id:
        return {"success": False, "message": "系统异常：操作员身份未识别，请重新登录后再试"}

    cid, err = await _resolve_customer(arguments)
    if err:
        return {"success": False, "message": err}
    order_type = arguments.get("order_type", "咨询")
    content = arguments.get("content", "")
    if not content or not content.strip():
        return {"success": False, "message": "工单内容不能为空"}
    if len(content) > 5000:
        return {"success": False, "message": "工单内容长度超限（最大5000字符）"}
    _VALID_ORDER_TYPES = {"投诉", "建议", "咨询", "风控", "其他"}
    if order_type not in _VALID_ORDER_TYPES:
        return {"success": False, "message": f"工单类型无效: {order_type}，可选: {', '.join(_VALID_ORDER_TYPES)}"}

    from app.config.database import async_session_factory
    async with async_session_factory() as db:
        if e := await _check_customer_status(cid, db):
            return {"success": False, "message": e}
        result = await create_work_order(body={
            "customer_id": cid, "order_type": order_type, "content": content, "submitter_id": operator_id,
        }, db=db)
        return {"success": result.code == 200, "message": result.message, "data": result.data}


# ---------- 查询类 ----------

async def _tool_query_product(arguments: dict, _op) -> dict:
    pid, err = await _resolve_product(arguments)
    if err:
        return {"success": False, "message": err}
    from app.config.database import async_session_factory
    async with async_session_factory() as db:
        result = await query_product(product_id=pid, db=db)
        return {"success": result.code == 200, "message": result.message, "data": result.data}


async def _tool_query_product_list(arguments: dict, _op) -> dict:
    from app.config.database import async_session_factory
    async with async_session_factory() as db:
        result = await list_products(
            risk_level=arguments.get("risk_level"),
            product_type=arguments.get("product_type"), db=db)
        ok = result.get("code") == 200 if isinstance(result, dict) else result.code == 200
        return {"success": ok, "data": result.get("data") if isinstance(result, dict) else result.data}


async def _tool_customer_holdings(arguments: dict, _op) -> dict:
    name = arguments.get("customer_name", "")
    found, data = await get_customer_products(name)
    if not found:
        return {"success": False, "message": data}
    if not data:
        return {"success": False, "message": f"客户 {name} 无持仓记录"}
    return {"success": True, "data": data}


async def _tool_suitable_products(arguments: dict, _op) -> dict:
    return {"success": True, "data": await get_suitable_products(arguments.get("risk_level", "R3"))}


# ---------- 审计日志查询 ----------

async def _tool_query_audit_log(arguments: dict, _op) -> dict:
    customer_name = arguments.get("customer_name", "")
    transaction_type = arguments.get("transaction_type", "")
    min_amount = arguments.get("min_amount", 0)
    days = arguments.get("days", 30)

    try:
        days = int(days)
        min_amount = float(min_amount)
    except (ValueError, TypeError):
        return {"success": False, "message": "days 和 min_amount 必须为数字"}
    if days < 1 or days > 365:
        return {"success": False, "message": "查询天数 days 超出范围（1-365）"}
    if min_amount < 0:
        return {"success": False, "message": "min_amount 不能为负数"}
    if min_amount > _MAX_AMOUNT:
        return {"success": False, "message": "min_amount 超过上限"}
    if transaction_type and transaction_type not in _TRANSACTION_TYPE_WHITELIST:
        return {"success": False,
                "message": f"无效的交易类型: {transaction_type}，可选: {', '.join(sorted(_TRANSACTION_TYPE_WHITELIST))}"}

    conditions = ["1=1"]
    params: dict = {"days": days}
    if customer_name:
        cid = await resolve_customer_id(customer_name)
        if not cid:
            return {"success": False, "message": f"未找到客户: {customer_name}"}
        conditions.append("t.customer_id = :cid")
        params["cid"] = cid
    if transaction_type:
        conditions.append("t.transaction_type = :type")
        params["type"] = transaction_type
    if min_amount > 0:
        conditions.append("t.amount >= :min_amt")
        params["min_amt"] = min_amount

    from app.config.database import async_session_factory
    async with async_session_factory() as db:
        result = await db.execute(text(f"""
            SELECT t.transaction_no, t.customer_id, t.product_id,
                   t.transaction_type, t.amount, t.shares, t.status,
                   t.operator_id, t.remark, t.create_time,
                   p.product_name, p.risk_level, u.real_name AS operator_name
            FROM fin_transaction t
            LEFT JOIN fin_product p ON t.product_id = p.id
            LEFT JOIN sys_user u ON t.operator_id = u.id
            WHERE {' AND '.join(conditions)}
              AND t.create_time >= DATE_SUB(NOW(), INTERVAL :days DAY)
            ORDER BY t.create_time DESC LIMIT 100
        """), params)
        rows = result.mappings().all()

    transactions = []
    for row in rows:
        transactions.append({
            "transaction_no": row["transaction_no"], "customer_id": row["customer_id"],
            "transaction_type": row["transaction_type"],
            "amount": float(row["amount"] or 0), "shares": float(row["shares"] or 0),
            "product_name": row["product_name"], "risk_level": row["risk_level"],
            "status": row["status"],
            "operator_name": row["operator_name"] or f"操作员{row['operator_id']}",
            "remark": row["remark"],
            "create_time": row["create_time"].strftime("%Y-%m-%d %H:%M:%S") if row["create_time"] else "",
        })
    return {"success": True, "data": {
        "customer_name": customer_name or "全部客户",
        "transaction_type": transaction_type or "全部类型",
        "min_amount": min_amount, "query_days": days,
        "transactions": transactions, "total_count": len(transactions),
    }}


# ---------- 客户全景视图 ----------

async def _tool_query_customer_panoramic(arguments: dict, _op) -> dict:
    customer_name = arguments.get("customer_name", "")
    cid = await resolve_customer_id(customer_name)
    if not cid:
        return {"success": False, "message": f"未找到客户: {customer_name}"}

    from app.config.database import async_session_factory
    async with async_session_factory() as db:
        user = (await db.execute(
            text("SELECT id, real_name, phone, email, balance, status, create_time FROM sys_user WHERE id = :cid"),
            {"cid": cid})).mappings().first()
        if not user:
            return {"success": False, "message": f"未找到客户: {customer_name}"}

        risk_level = await _get_customer_risk_level(cid, db)
        profile = (await db.execute(text(
            "SELECT risk_level, risk_score, total_assets, investment_experience, confidence_score "
            "FROM fin_customer_profile WHERE customer_id = :cid"), {"cid": cid})).mappings().first()

        found, holdings_data = await get_customer_products(customer_name)
        holdings = holdings_data if found and isinstance(holdings_data, list) else []
        total_val = sum(float(h.get("current_value", 0)) for h in holdings)

        recent_txs = (await db.execute(text("""
            SELECT transaction_type, amount, create_time FROM fin_transaction
            WHERE customer_id = :cid AND create_time >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            ORDER BY create_time DESC LIMIT 10
        """), {"cid": cid})).mappings().all()

        alerts = (await db.execute(text("""
            SELECT alert_type, alert_level, status, create_time FROM fin_risk_alert
            WHERE customer_id = :cid ORDER BY create_time DESC LIMIT 5
        """), {"cid": cid})).mappings().all()

    similar = await get_customer_community(threshold=0.3)
    related = [s for s in similar
               if s.get("customer_1_id") == cid or s.get("customer_2_id") == cid][:5]
    industry = await get_industry_distribution(customer_name)

    # 手机号/邮箱脱敏
    _phone = user.get("phone", "") or ""
    _email = user.get("email", "") or ""
    phone_masked = (_phone[:3] + "****" + _phone[-4:]) if len(_phone) >= 7 else _phone
    email_masked = (_email[:2] + "***" + _email[_email.index("@"):]) if "@" in _email else _email

    return {"success": True, "data": {
        "customer_id": cid, "customer_name": customer_name,
        "basic_info": {
            "real_name": user["real_name"], "phone": phone_masked, "email": email_masked,
            "balance": float(user.get("balance", 0)), "status": user.get("status", "正常"),
            "register_time": user["create_time"].strftime("%Y-%m-%d") if user.get("create_time") else "",
        },
        "risk_info": {
            "risk_level": risk_level or "未评估",
            "risk_score": float(profile["risk_score"]) if profile and profile.get("risk_score") else 0,
            "confidence": float(profile["confidence_score"]) if profile and profile.get("confidence_score") else 0,
            "total_assets": float(profile["total_assets"]) if profile and profile.get("total_assets") else 0,
            "investment_experience": profile.get("investment_experience", "未知") if profile else "未知",
        },
        "holdings": {"count": len(holdings), "total_value": total_val, "details": holdings[:10]},
        "recent_transactions": [
            {"type": tx["transaction_type"], "amount": float(tx.get("amount", 0)),
             "time": tx["create_time"].strftime("%Y-%m-%d %H:%M") if tx.get("create_time") else ""}
            for tx in recent_txs
        ],
        "risk_alerts": [
            {"type": a["alert_type"], "level": a["alert_level"], "status": a["status"],
             "time": a["create_time"].strftime("%Y-%m-%d") if a.get("create_time") else ""}
            for a in alerts
        ],
        "related_customers": related, "industry_distribution": industry[:5],
    }}


# ---------- 客户列表 ----------

async def _tool_query_customer_list(arguments: dict, _op) -> dict:
    limit = arguments.get("limit", 50)
    risk_level = arguments.get("risk_level", "")
    status = arguments.get("status", "")

    try:
        limit = int(limit)
    except (ValueError, TypeError):
        return {"success": False, "message": "limit 必须为整数"}
    if limit < 1 or limit > 500:
        return {"success": False, "message": "limit 超出范围（1-500）"}

    conditions = ["u.user_type = 'CUSTOMER'"]
    params: dict = {"limit": limit}
    if status:
        conditions.append("u.status = :status")
        params["status"] = status

    from app.config.database import async_session_factory
    async with async_session_factory() as db:
        if risk_level:
            base_query = f"""
                SELECT u.id, u.real_name, u.phone, u.email, u.balance, u.status, u.create_time
                FROM sys_user u
                INNER JOIN (
                    SELECT customer_id, risk_level,
                           ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY create_time DESC) AS rn
                    FROM fin_risk_assessment
                ) ra ON ra.customer_id = u.id AND ra.rn = 1
                WHERE {' AND '.join(conditions)} AND ra.risk_level = :risk_level
                ORDER BY u.create_time DESC LIMIT :limit
            """
            params["risk_level"] = risk_level
        else:
            base_query = f"""
                SELECT u.id, u.real_name, u.phone, u.email, u.balance, u.status, u.create_time
                FROM sys_user u WHERE {' AND '.join(conditions)}
                ORDER BY u.create_time DESC LIMIT :limit
            """
        result = await db.execute(text(base_query), params)
        customers = result.mappings().all()

    customer_list = [{
        "id": c["id"], "name": c["real_name"], "phone": c["phone"], "email": c["email"],
        "balance": float(c["balance"] or 0), "status": c["status"],
        "register_time": c["create_time"].strftime("%Y-%m-%d") if c["create_time"] else "",
    } for c in customers]

    return {"success": True, "data": {
        "customers": customer_list, "total_count": len(customer_list), "limit": limit,
        "filters": {"risk_level": risk_level, "status": status},
    }}


# ==================== 工具注册表 ====================

_TOOL_REGISTRY: dict[str, callable] = {
    "purchase_product": _tool_purchase,
    "query_product": _tool_query_product,
    "query_product_list": _tool_query_product_list,
    "get_customer_holdings": _tool_customer_holdings,
    "get_suitable_products": _tool_suitable_products,
    "redeem_product": _tool_redeem,
    "transfer_funds": _tool_transfer,
    "redo_assessment": _tool_redo_assessment,
    "update_contact": _tool_update_contact,
    "report_suspicious": _tool_report_suspicious,
    "create_work_order": _tool_create_work_order,
    "query_audit_log": _tool_query_audit_log,
    "query_customer_panoramic": _tool_query_customer_panoramic,
    "query_customer_list": _tool_query_customer_list,
}


async def execute_tool(tool_name: str, arguments: dict, operator_id: int = None) -> dict:
    handler = _TOOL_REGISTRY.get(tool_name)
    if handler is None:
        return {"success": False, "message": f"未知工具: {tool_name}"}
    try:
        return await handler(arguments, operator_id)
    except Exception as exc:
        logger.error("工具执行失败 tool=%s: %s", tool_name, exc)
        return {"success": False, "message": f"工具执行异常: {str(exc)}"}


def register_tool(name: str, handler: callable) -> None:
    _TOOL_REGISTRY[name] = handler


# ==================== 对话入口 ====================

async def operator_chat(
    message: str,
    session_id: str = "",
    user_id: int = 0,
    user_role: str = "理财顾问",
) -> dict:
    if not session_id:
        session_id = uuid.uuid4().hex

    memory = SessionMemory(session_id)
    await memory.add_message("user", message)

    msg_stripped = message.strip()

    # 0. 确认/取消
    _is_confirm = bool(_CONFIRM_RE.match(msg_stripped))
    _note_match = _CONFIRM_RE.match(msg_stripped)
    _parsed_note = _note_match.group("note").strip() if _note_match and _note_match.group("note") else ""

    if _is_confirm:
        pending = await _load_pending_confirm(session_id)
        if pending:
            note_required = pending.get("note_required", False)
            if note_required and not _parsed_note:
                reply = ("⚠️ 该操作金额超过 50 万元，请回复备注原因。\n"
                         "格式：确认 备注：<原因>\n例如：确认 备注：客户主动要求购买")
                await memory.add_message("assistant", reply)
                return {"reply": reply, "action": pending["action"],
                        "params": pending["arguments"], "status": "note_required", "session_id": session_id}

            await _delete_pending_confirm(session_id)
            action = pending["action"]
            arguments = pending["arguments"]
            if _parsed_note:
                arguments["operator_note"] = _parsed_note
            summary = pending.get("summary", _build_confirmation_summary(action, arguments))
            result = await execute_tool(action, arguments, operator_id=pending["user_id"])
            if result.get("success"):
                reply = f"✅ 已确认执行：{summary}\n\n" + _format_success_reply(action, arguments, result.get("data"))
                status = "ok"
                await _create_audit_work_order(action, arguments, result.get("data", {}), pending["user_id"])
                await publish_operation_event(action=action, arguments=arguments,
                                              data=result.get("data", {}), user_id=user_id)
            else:
                reply = f"❌ 确认操作执行失败：{summary}\n原因：{result.get('message', '')}"
                status = "error"
            await memory.add_message("assistant", reply)
            await _archive_memory(memory, user_id)
            return {"reply": reply, "action": action, "params": arguments,
                    "status": status, "session_id": session_id}
        else:
            reply = "没有待确认的操作，请问您需要办理什么业务？"
            await memory.add_message("assistant", reply)
            await _archive_memory(memory, user_id)
            return {"reply": reply, "action": None, "params": {}, "status": "ok", "session_id": session_id}

    if msg_stripped in ("取消", "不", "否", "n", "no"):
        pending = await _load_pending_confirm(session_id)
        if pending:
            await _delete_pending_confirm(session_id)
            reply = f"已取消 {pending['action']} 操作。"
            await memory.add_message("assistant", reply)
            await _archive_memory(memory, user_id)
            return {"reply": reply, "action": None, "params": {}, "status": "cancelled", "session_id": session_id}

    # 1. 权限
    allowed_actions = RBAC_PERMISSIONS.get(user_role, [])
    if not allowed_actions:
        reply = f"抱歉，角色（{user_role}）没有任何业务操作权限，请联系管理员。"
        await memory.add_message("assistant", reply)
        await _archive_memory(memory, user_id)
        return {"reply": reply, "action": None, "params": {}, "status": "permission_denied", "session_id": session_id}
    available_tools = [t for t in TOOLS if t["function"]["name"] in allowed_actions]

    # 2. LLM
    history = await memory.get_messages(max_tokens=2048)
    cross_session = await _recall_recent_operations(user_id)
    sys_content = SYSTEM_PROMPT + (f"\n\n# 你的近期操作记录\n{cross_session}" if cross_session else "")
    llm_messages = [{"role": "system", "content": sys_content}] + history

    try:
        response = await llm_client.chat.completions.create(
            model=settings.llm.openai_model_chat, messages=llm_messages,
            tools=available_tools, tool_choice="auto",
            temperature=settings.llm.openai_temperature)
    except Exception as e:
        reply = f"抱歉，系统暂时无法处理您的请求: {e}"
        await memory.add_message("assistant", reply)
        await _archive_memory(memory, user_id)
        return {"reply": reply, "action": None, "params": {}, "status": "error", "session_id": session_id}

    msg = response.choices[0].message

    if not msg.tool_calls:
        reply = mask_text(msg.content or "请问您需要办理什么业务？")
        await memory.add_message("assistant", reply)
        await _archive_memory(memory, user_id)
        return {"reply": reply, "action": None, "params": {}, "status": "ok", "session_id": session_id}

    # 4. 处理工具调用
    replies = []
    actions_taken = []

    for tool_call in msg.tool_calls:
        action = tool_call.function.name
        try:
            arguments = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            replies.append(f"⚠️ 工具 {action} 参数解析失败，已跳过。")
            continue

        if not check_permission(user_role, action):
            replies.append(f"抱歉，您的角色（{user_role}）没有执行 {action} 的权限")
            actions_taken.append({"action": action, "status": "permission_denied"})
            continue

        # 6. 二次确认（赎回按估算金额判断）
        if action == "redeem_product":
            shares_val, amt_err = _safe_float(arguments.get("shares", 0), "赎回份额")
            if amt_err:
                replies.append(f"⚠️ {amt_err}，无法执行 {action}")
                actions_taken.append({"action": action, "status": "param_error"})
                continue
            _cid = await resolve_customer_id(arguments.get("customer_name", ""))
            _pid = await resolve_product_id(arguments.get("product_name", ""))
            confirm_value = 0.0
            if _cid and _pid:
                from app.config.database import async_session_factory
                async with async_session_factory() as _db:
                    _h = (await _db.execute(
                        text("SELECT shares, current_value, cost_amount FROM fin_holdings "
                             "WHERE customer_id = :cid AND product_id = :pid AND status = '持有中'"),
                        {"cid": _cid, "pid": _pid})).mappings().first()
                    if _h and _h["shares"] and _h["shares"] > 0:
                        rv = _h["current_value"]
                        if rv is None or float(rv) <= 0:
                            rv = _h.get("cost_amount") or 0
                        confirm_value = shares_val * (float(rv) / float(_h["shares"]))
        else:
            confirm_value, amt_err = _safe_float(arguments.get("amount", 0), "金额")
            if amt_err and needs_confirmation(action, 0):
                replies.append(f"⚠️ {amt_err}，无法执行 {action}")
                actions_taken.append({"action": action, "status": "param_error"})
                continue

        if needs_confirmation(action, confirm_value):
            note_required = confirm_value >= _LARGE_AMOUNT_NOTE_THRESHOLD
            saved = await _save_pending_confirm(
                session_id, action, arguments, user_id, user_role, note_required=note_required)
            if not saved:
                replies.append(f"系统暂忙，无法处理大额 {action} 操作，请稍后再试")
                actions_taken.append({"action": action, "status": "system_error"})
                continue
            summary = _build_confirmation_summary(action, arguments)
            pending_count = len(msg.tool_calls) - len(actions_taken) - 1
            reply = f"⚠️ 大额操作需确认：{summary}\n\n请回复 '确认' 执行，或 '取消' 放弃。"
            if replies:
                reply = "\n\n".join(replies) + "\n\n" + reply
            if pending_count > 0:
                reply += f"\n\n（另有 {pending_count} 个操作待处理，确认后将一并执行）"
            await memory.add_message("assistant", reply)
            await _archive_memory(memory, user_id)
            return {"reply": reply, "action": action, "params": arguments,
                    "status": "confirm_required", "session_id": session_id}

        # 7. 执行
        result = await execute_tool(action, arguments, operator_id=user_id)
        actions_taken.append({"action": action, "params": arguments})

        if result.get("success"):
            replies.append(_format_success_reply(action, arguments, result.get("data")))
            await _create_audit_work_order(action, arguments, result.get("data", {}), user_id)
            await publish_operation_event(action=action, arguments=arguments,
                                          data=result.get("data", {}), user_id=user_id)
        else:
            replies.append(result.get("message", f"{action} 操作失败"))

    combined_reply = mask_text("\n\n".join(replies)) if replies else "请问您需要办理什么业务？"
    final_status = "ok" if any(a.get("status") != "permission_denied" for a in actions_taken) else "permission_denied"

    await memory.add_message("assistant", combined_reply)
    await _archive_memory(memory, user_id)

    return {
        "reply": combined_reply,
        "action": actions_taken[0]["action"] if actions_taken else None,
        "params": actions_taken[0].get("params", {}) if actions_taken else {},
        "status": final_status, "session_id": session_id,
    }


# ==================== 回复格式化 ====================

def _format_success_reply(action: str, arguments: dict, data: dict) -> str:
    if action == "purchase_product":
        return (f"✅ 申购成功！\n• 交易流水号: {data.get('transaction_no', '')}\n"
                f"• 产品: {data.get('product_name', '')}\n• 金额: {data.get('amount', 0)} 元\n"
                f"• 份额: {data.get('shares', 0)}\n• 适用净值日期: {data.get('nav_date', '')}")
    if action == "redeem_product":
        return (f"✅ 赎回成功！\n• 交易流水号: {data.get('transaction_no', '')}\n"
                f"• 赎回份额: {data.get('shares', 0)}\n• 到账金额: {data.get('amount', 0)} 元")
    if action == "transfer_funds":
        return (f"✅ 转账成功！\n• 流水号: {data.get('transaction_no', '')}\n"
                f"• 金额: {data.get('amount', 0)} 元\n• 转入客户ID: {data.get('to_customer_id', '')}")
    if action == "redo_assessment":
        return (f"✅ 风评完成！\n• 客户ID: {data.get('customer_id', '')}\n"
                f"• 风险等级: {data.get('risk_level', '')}\n• 评分: {data.get('score', 0)}\n"
                f"• 有效期至: {data.get('valid_until', '')}")
    if action == "update_contact":
        return f"✅ 信息更新成功！\n• 客户ID: {data.get('customer_id', '')}\n• 更新字段: {data.get('field', '')}"
    if action == "report_suspicious":
        return f"✅ 可疑交易已上报！\n• 预警编号: {data.get('alert_no', '')}\n• 客户ID: {data.get('customer_id', '')}"
    if action == "create_work_order":
        return f"✅ 工单创建成功！\n• 工单号: {data.get('work_order_no', '')}\n• 类型: {data.get('order_type', '')}"
    if action == "query_product":
        return (f"📊 产品详情:\n• 名称: {data.get('product_name', '')}\n• 代码: {data.get('product_code', '')}\n"
                f"• 类型: {data.get('product_type', '')}\n• 风险等级: {data.get('risk_level', '')}\n"
                f"• 预期收益: {data.get('expected_return', 0)}%\n• 起投金额: {data.get('min_amount', 0)} 元")
    if action == "query_product_list":
        products = data if isinstance(data, list) else []
        if not products:
            return "当前没有符合条件的在售产品。"
        lines = ["📋 在售产品列表:"]
        for p in products[:5]:
            lines.append(f"• {p.get('product_name', '')} ({p.get('risk_level', '')}) "
                         f"预期收益 {p.get('expected_return', 0)}%")
        return "\n".join(lines)
    if action == "get_customer_holdings":
        holdings = data if isinstance(data, list) else []
        if not holdings:
            return "该客户暂无持仓。"
        lines = ["💼 客户持仓:"]
        for h in holdings:
            lines.append(f"• {h.get('product_name', '')}: {h.get('shares', 0)} 份, "
                         f"市值 {h.get('current_value', 0)} 元, 收益 {h.get('profit_ratio', 0)}%")
        return "\n".join(lines)
    if action == "get_suitable_products":
        products = data if isinstance(data, list) else []
        if not products:
            return "没有匹配的产品。"
        lines = ["🎯 适当性匹配产品:"]
        for p in products[:5]:
            lines.append(f"• {p.get('product_name', '')} ({p.get('risk_level', '')}) "
                         f"预期收益 {p.get('expected_return', 0)}%")
        return "\n".join(lines)
    if action == "query_audit_log":
        d = data
        txs = d.get("transactions", [])
        lines = [f"📋 操作审计日志\n• 查询范围: {d.get('customer_name', '')} | "
                 f"{d.get('transaction_type', '')} | 近{d.get('query_days', 30)}天"]
        if not txs:
            lines.append("\n✅ 未找到符合条件的操作记录")
            return "\n".join(lines)
        lines.append(f"• 查询结果: {d.get('total_count', 0)}条记录")
        type_names = {"purchase": "申购", "redeem": "赎回", "transfer_out": "转出", "transfer_in": "转入"}
        for tx in txs[:20]:
            t = tx.get("transaction_type", "")
            lines.append(f"  • [{tx.get('create_time', '')}] {type_names.get(t, t)} "
                         f"{tx.get('amount', 0):,.2f}元 | {tx.get('product_name', '')}")
        if len(txs) > 20:
            lines.append(f"  ... 还有 {len(txs) - 20} 条记录")
        return "\n".join(lines)
    if action == "query_customer_panoramic":
        p = data
        lines = [f"📊 客户全景视图 — {p.get('customer_name', '')}（ID: {p.get('customer_id', '')}）"]
        b = p.get("basic_info", {})
        lines.append(f"\n👤 基本信息:\n  • 姓名: {b.get('real_name', '')}\n  • 手机: {b.get('phone', '')}\n"
                      f"  • 邮箱: {b.get('email', '')}\n  • 余额: {b.get('balance', 0):,.2f} 元")
        r = p.get("risk_info", {})
        lines.append(f"\n🛡️ 风险信息:\n  • 风险等级: {r.get('risk_level', '未评估')}\n"
                      f"  • 总资产: {r.get('total_assets', 0):,.2f} 元")
        h = p.get("holdings", {})
        lines.append(f"\n💼 持仓: {h.get('count', 0)}只 / {h.get('total_value', 0):,.2f} 元")
        return "\n".join(lines)
    if action == "query_customer_list":
        d = data
        customers = d.get("customers", [])
        lines = [f"👥 客户列表 — {d.get('total_count', 0)}位"]
        for c in customers[:20]:
            icon = "✅" if c.get("status") == "正常" else "⚠️"
            lines.append(f"  • {icon} {c.get('name', '')} (ID:{c.get('id', '')}) | "
                         f"余额{c.get('balance', 0):,.2f}元 | {c.get('status', '')}")
        if len(customers) > 20:
            lines.append(f"  ... 还有 {len(customers) - 20} 位")
        return "\n".join(lines)
    return f"操作 {action} 执行成功。"
