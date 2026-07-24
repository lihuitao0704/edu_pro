import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.common_services.context_manager.entity_tracker import EntityTracker
from app.common_services.context_manager.memory_manager import MemoryManager
from app.common_services.context_manager.models import AgentResult
from app.common_services.orchestration.response_enhancer import ResponseEnhancer
from app.common_services.safety_guard.input_filter import InputSafetyFilter
from app.common_services.safety_guard.output_filter import OutputSafetyFilter
from app.common_services.trace_service.trace_service import TraceService
from app.model.schemas import UnifiedChatResponse

# ── C4 风控联动：敏感操作关键词 ──
_SENSITIVE_PATTERNS = [
    # ── 大额敏感操作（明确涉及金额门槛） ──
    r'大额.*(?:转账|转出|汇款|赎回|申购|买入|购买)',
    r'(?:转账|转出|汇款|赎回).*大额',
    r'(?:大额|大量)[^。]*?(?:赎回|取出|提现|申购|买入|购买)',
    # ── 有意向的操作（带 要/想/帮/请/给/进行/办理 等意愿词） ──
    r'(?:我要|我想|请帮我|帮我|请|准备|打算|需要|进行|办理).*(?:转账|转出|汇款|赎回)',
    r'(?:我要|我想|请帮我|帮我|请|准备|打算|需要).*(?:申购|买入|购买)',
    # ── 怎么执行某操作（无意向，但涉及金额需关注） ──
    r'(?:怎么|如何)(?:转账|汇款|赎回)',
    # ── "想"类意图 ──
    r'想.*(?:转账|转出|汇款|赎回|申购)',
]

_RISK_AWARE_BLOCK_REPLY_HIGH = (
    "⚠️ **风控拦截**：系统检测到您的账户当前处于**高风险关注状态**，"
    "该操作已被暂停。请联系您的理财顾问或拨打客服热线处理。"
)

_RISK_AWARE_REPLY_MEDIUM = (
    "\n\n---\nℹ️ **温馨提示（C4联动）**：您的账户近期有交易活动触发风控关注。"
    "如涉及大额交易，系统可能会要求二次确认。如有疑问请联系客服。"
)


class ChatOrchestrator:
    """Shared execution pipeline around the existing Router Agent.

    The router and business agents remain domain adapters. Cross-cutting
    behavior is intentionally enforced here so future agents inherit it.
    """

    def __init__(
        self,
        router: Any,
        db=None,
        memory_manager: MemoryManager | None = None,
        entity_tracker: EntityTracker | None = None,
        input_filter: InputSafetyFilter | None = None,
        output_filter: OutputSafetyFilter | None = None,
        enhancer: ResponseEnhancer | None = None,
        trace_service: TraceService | None = None,
    ):
        self.router = router
        self.db = db
        self.memory_manager = memory_manager or MemoryManager(db=db)
        self.entity_tracker = entity_tracker or EntityTracker()
        self.input_filter = input_filter or InputSafetyFilter()
        self.output_filter = output_filter or OutputSafetyFilter()
        self.enhancer = enhancer or ResponseEnhancer()
        self.trace_service = trace_service or TraceService()

    async def handle(
        self,
        message: str,
        session_id: str,
        actor_id: int,
        actor_role: str,
        customer_id: int | None = None,
    ) -> UnifiedChatResponse:
        session_id = session_id or uuid.uuid4().hex
        trace_id = uuid.uuid4().hex
        input_decision = self.input_filter.inspect(message)
        trace = self.trace_service.start(
            trace_id, session_id, actor_id, input_decision.sanitized_text
        )
        if input_decision.blocked:
            trace.finish("blocked", input_decision.user_message)
            return UnifiedChatResponse(
                intent="safety_block",
                agent="safety_guard",
                confidence=1.0,
                session_id=session_id,
                reply=input_decision.user_message,
                data={"trace_id": trace_id, "safety_flags": input_decision.matched_rules},
            )

        # ── C4 风控联动：检查是否敏感操作，查询客户风险状态 ──
        # 用 customer_id（业务客户）兜底 actor_id（JWT身份），
        # 确保 Mock 模式和理财顾问代操作场景都能查到正确的风险数据
        risk_context = await self._check_risk_context(
            customer_id if customer_id is not None else actor_id,
            input_decision.sanitized_text,
        )
        is_high_risk_sensitive = (
            risk_context["is_sensitive"]
            and risk_context["risk_level"] == "high"
        )
        if is_high_risk_sensitive:
            # 高风险 + 敏感操作 → 直接拦截，不路由到任何 Agent
            import logging
            logger = logging.getLogger(__name__)
            logger.info(
                "C4联动拦截 | user=%s | msg=%s | risk_level=high",
                actor_id, input_decision.sanitized_text[:50],
            )
            trace.finish("blocked", _RISK_AWARE_BLOCK_REPLY_HIGH)
            return UnifiedChatResponse(
                intent="risk_block",
                agent="safety_guard",
                confidence=1.0,
                session_id=session_id,
                reply=_RISK_AWARE_BLOCK_REPLY_HIGH,
                data={
                    "trace_id": trace_id,
                    "risk_level": "high",
                    "block_reason": "高风险客户敏感操作拦截",
                    "safety_flags": ["c4_risk_block"],
                },
            )

        # ── 加载上下文 & 追踪实体 ──
        previous_context = await self.memory_manager.load_context(session_id, actor_id)
        entities = self.entity_tracker.track(
            input_decision.sanitized_text, previous_context.get("entities", {})
        )

        # ── 构造路由上下文（含风控信息） ──
        route_context: dict[str, Any] = {
            "entities": {**previous_context.get("entities", {}), **entities},
        }
        if risk_context["is_sensitive"] and risk_context["risk_level"] == "medium":
            # 中风险 + 敏感操作：注入风控上下文，下游 Agent 可在回复中附加提示
            route_context["risk_context"] = risk_context
            route_context["risk_warning"] = _RISK_AWARE_REPLY_MEDIUM

        routed = await self.router.route(
            message=input_decision.sanitized_text,
            session_id=session_id,
            user_id=actor_id,
            user_role=actor_role,
            context=route_context,
        )
        trace.add_span("router_agent")
        trace.add_span(routed.agent)
        agent_result = AgentResult(
            reply=routed.reply,
            intent=routed.intent,
            agent_name=routed.agent,
            confidence=routed.confidence,
            data=routed.data if isinstance(routed.data, dict) else None,
            source_count=len((routed.data or {}).get("sources", [])) if isinstance(routed.data, dict) else 0,
            fallback_used=bool(isinstance(routed.data, dict) and routed.data.get("fallback_used")),
        )
        agent_result = self.enhancer.enhance(agent_result)

        # ── 中风险敏感操作：在回复末尾附加风控温馨提示 ──
        if route_context.get("risk_warning"):
            agent_result.reply = agent_result.reply.rstrip() + route_context["risk_warning"]

        output_decision = self.output_filter.inspect(agent_result.reply)
        agent_result.reply = output_decision.safe_reply
        context = self.memory_manager.save_context(
            session_id,
            actor_id,
            entities,
            last_intent=agent_result.intent,
            last_agent=agent_result.agent_name,
        )
        trace.finish("ok" if output_decision.allowed else "sanitized", agent_result.reply)
        data = dict(agent_result.data or {})
        data.update({
            "trace_id": trace_id,
            "context": context,
            "suggested_questions": agent_result.suggested_questions,
            "safety_flags": output_decision.matched_rules,
            "trace": {"total_latency_ms": trace.total_latency_ms, "spans": trace.spans},
        })
        return UnifiedChatResponse(
            intent=agent_result.intent,
            agent=agent_result.agent_name,
            confidence=agent_result.confidence,
            session_id=session_id,
            reply=agent_result.reply,
            data=data,
        )

    # ════════════════════════════════════════════════════════════
    # C4 风控联动：敏感操作检测 + 风险上下文查询
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _is_sensitive_query(message: str) -> bool:
        """检测用户消息是否涉及敏感金融操作"""
        for pattern in _SENSITIVE_PATTERNS:
            if re.search(pattern, message):
                return True
        return False

    async def _check_risk_context(self, user_id: int, message: str) -> dict:
        """
        统一风控上下文检查。

        检测敏感操作关键词，查询客户风险状态。
        数据来源（按优先级）：
          1. Redis cs_risk_ctx:{user_id} — C4事件频道实时写入的上下文
          2. MySQL fin_customer_profile.risk_flag — 画像风险标记
          3. MySQL fin_risk_alert — 近期预警统计

        Returns:
            {is_sensitive: bool, risk_level: "high"|"medium"|"low"|None,
             alert_count: int, has_alert: bool}
        """
        result: dict[str, Any] = {
            "is_sensitive": False,
            "risk_level": None,
            "alert_count": 0,
            "has_alert": False,
        }

        # 1. 检测是否敏感操作
        if not self._is_sensitive_query(message):
            return result
        result["is_sensitive"] = True
        _logger = __import__("logging").getLogger(__name__)

        # 2. 查询 Redis C4 上下文
        try:
            from app.config.database import get_redis

            r = await get_redis()
            ctx = await r.get(f"cs_risk_ctx:{user_id}")
            if ctx:
                ctx_data = json.loads(ctx)
                if ctx_data.get("has_alert"):
                    result["has_alert"] = True
                    _logger.info("C4联动: 客户%s Redis风险上下文命中", user_id)
        except Exception as e:
            _logger.debug("C4联动 Redis查询失败(非阻断): %s", e)

        # 3. 查询 MySQL 画像风险标记
        if self.db is not None:
            try:
                row = await self.db.execute(
                    text(
                        "SELECT risk_flag FROM fin_customer_profile "
                        "WHERE customer_id = :cid"
                    ),
                    {"cid": user_id},
                )
                profile_row = row.first()
                if profile_row:
                    flag = profile_row[0]
                    if flag == "high":
                        result["risk_level"] = "high"
                    elif flag == "warning":
                        result["risk_level"] = "medium"
                    elif flag == "normal":
                        result["risk_level"] = "low"
            except Exception as e:
                _logger.debug("C4联动 画像查询失败(非阻断): %s", e)

            # 4. 查询近期预警数量
            try:
                thirty_days_ago = datetime.now() - timedelta(days=30)
                row = await self.db.execute(
                    text(
                        "SELECT COUNT(*) FROM fin_risk_alert "
                        "WHERE customer_id = :cid AND create_time >= :since"
                    ),
                    {"cid": user_id, "since": thirty_days_ago},
                )
                count = row.scalar() or 0
                result["alert_count"] = count
                if count > 0:
                    result["has_alert"] = True
                    if count >= 3 and result["risk_level"] != "high":
                        result["risk_level"] = "high"
                    elif count >= 1 and result["risk_level"] is None:
                        result["risk_level"] = "medium"
            except Exception as e:
                _logger.debug("C4联动 预警统计失败(非阻断): %s", e)

        return result
