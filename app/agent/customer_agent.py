"""
Agent Service — 客服Agent核心编排逻辑
完整流程：会话管理 → 意图路由 → 记忆召回 → RAG检索 → 结果组装 → 安全审核 → 归档
C5 反向联动：对话中检测风控信号 → 通知风控Agent → 反馈闭环
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.model.schemas import CustomerChatResponse, SourceReference
from app.service.intent_service import get_intent_service
from app.service.rag_service import get_rag_service
from app.service.memory_service import get_memory_service
from app.service.safety_service import get_safety_service
from app.service.memory_recall_service import get_memory_recall_service
from app.tool.llm_tool import get_llm_tool
from app.tool.risk_signal_rules import detect_l1_signals, should_trigger_l3_detection, RiskSignal, LLM_SIGNAL_CLASSIFICATION_PROMPT
from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger("service.agent")

# 缓存 Prompt 文件内容，避免每次请求都同步读取文件
_chitchat_prompt_cache: Optional[str] = None
_customer_prompt_cache: Optional[str] = None


def _load_chitchat_prompt() -> str:
    global _chitchat_prompt_cache
    if _chitchat_prompt_cache is None:
        prompt_path = Path(__file__).parent.parent / "prompts" / "chitchat_reply.txt"
        if prompt_path.exists():
            _chitchat_prompt_cache = prompt_path.read_text(encoding="utf-8")
        else:
            _chitchat_prompt_cache = "你是XX科技智能财富管家的AI客服助手，请友好地回复用户，并引导回金融业务话题。"
    return _chitchat_prompt_cache


def _load_customer_prompt() -> str:
    global _customer_prompt_cache
    if _customer_prompt_cache is None:
        prompt_path = Path(__file__).parent.parent / "prompts" / "customer_system.txt"
        if prompt_path.exists():
            _customer_prompt_cache = prompt_path.read_text(encoding="utf-8")
        else:
            _customer_prompt_cache = "你是XX科技智能财富管家的AI客服助手，请基于参考资料回答客户问题。"
    return _customer_prompt_cache


class CustomerServiceAgent:
    """智能客服Agent核心类（含 C4 风控联动）"""

    # C4 风控联动：敏感操作关键词 → 风险提示模板
    SENSITIVE_KEYWORDS = {
        "大额转账": ["大额转账", "转账", "汇款", "大额"],
        "赎回": ["赎回", "取出", "提现"],
        "大额申购": ["大额申购", "大额买入", "大笔买入"],
    }

    RISK_AWARE_TEMPLATES = {
        "high": (
            "⚠️ **风控提示（C4联动）**：您的账户当前处于高风险关注状态。"
            "大额交易可能触发风控审核，建议联系您的理财顾问或拨打客服热线确认交易细节。"
            "为确保您的资金安全，部分大额操作可能需要额外验证。"
        ),
        "medium": (
            "ℹ️ **温馨提示（C4联动）**：您的账户近期有交易活动触发风控关注。"
            "如涉及大额交易，系统可能会要求二次确认。如有疑问请联系客服。"
        ),
        "low": (
            "✅ 您的账户风险状态正常，可正常办理业务。"
        ),
    }

    def __init__(self, db: AsyncSession):
        self.db = db
        self.intent_service = get_intent_service()
        self.rag_service = get_rag_service(db)
        self.memory = get_memory_service(db)
        self.safety = get_safety_service()
        self.llm = get_llm_tool()
        self.memory_recall = get_memory_recall_service()
        self.settings = get_settings()

    async def handle(self, session_id: str, user_id: int, message: str) -> CustomerChatResponse:
        """
        处理用户消息的主流程

        Args:
            session_id: 会话 ID
            user_id: 用户 ID
            message: 用户消息
        Returns:
            CustomerChatResponse
        """
        logger.info(f"客服Agent收到消息 | session={session_id} | user={user_id} | msg={message[:50]}...")

        # 0. 用户输入安全过滤（阻断恶意/不当内容发给LLM）
        is_safe, block_reason = await self.safety.filter_user_input(message)
        if not is_safe:
            return CustomerChatResponse(
                reply=block_reason or "您的输入包含不当内容，请重新描述。",
                sources=[],
                session_id=session_id,
                intent="blocked",
                confidence=1.0,
            )

        # 1. 加载短期记忆（同 session 多轮）
        history = await self.memory.get_history(session_id)

        # 1b. 跨 session 记忆召回（画像摘要 + 历史偏好 + 近期对话）
        user_profile = await self.memory_recall.build_user_profile_summary(self.db, user_id)
        historical_preferences = await self.memory_recall.recall_historical_preferences(self.db, user_id)
        historical_conversations = await self.memory_recall.recall_recent_conversations(self.db, user_id)

        # 2. 意图识别
        intent, intent_confidence = await self.intent_service.classify(message, history)

        # 2b. C4 风控联动：检测敏感操作 + 查询风险上下文
        risk_context = {}
        is_sensitive = self._is_sensitive_query(message)
        if is_sensitive:
            risk_context = await self._query_risk_context(user_id)
            logger.info(
                "C4联动触发 | user=%s | msg=%s | risk_level=%s | alerts=%s",
                user_id, message[:30], risk_context.get("risk_level"), risk_context.get("alert_count"),
            )

        # 2c. C5 反向联动：风控信号检测（L1关键词 + L2行为模式 + L3 LLM辅助）
        detected_signal = await self._detect_risk_signals(
            session_id=session_id,
            user_id=user_id,
            message=message,
            history=history,
        )

        # 3. 根据意图执行对应逻辑
        if intent == "transfer_human":
            reply = "正在为您转接人工客服，请稍候..."
            # C4 风控联动：转人工时也附加风险提示
            if is_sensitive and risk_context.get("risk_level"):
                risk_reply = self._get_risk_aware_reply(risk_context)
                if risk_reply:
                    reply = risk_reply + "\n\n" + reply
            # C5 反馈闭环：如果检测到信号，附加安抚话术
            if detected_signal:
                feedback_reply = self._get_signal_feedback_reply(detected_signal)
                if feedback_reply:
                    reply = feedback_reply + "\n\n" + reply
            sources = []

        elif intent == "chitchat":
            reply = await self._handle_chitchat(message, history)
            # C4 风控联动：即使是闲聊，也检测敏感词并附加风险提示
            if is_sensitive and risk_context.get("risk_level"):
                risk_reply = self._get_risk_aware_reply(risk_context)
                if risk_reply:
                    reply = risk_reply + "\n\n---\n\n" + reply
            # C5 反馈闭环
            if detected_signal:
                feedback_reply = self._get_signal_feedback_reply(detected_signal)
                if feedback_reply:
                    reply = feedback_reply + "\n\n---\n\n" + reply
            sources = []

        else:
            # RAG 检索
            knowledge_type = self.intent_service.get_knowledge_type(intent)
            if not knowledge_type:
                knowledge_type = "product_knowledge"

            rag_results = await self.rag_service.retrieve(
                query=message,
                knowledge_type=knowledge_type,
            )

            # 置信度检测
            check = await self.safety.check_confidence(rag_results, intent_confidence)
            if check["should_fallback"]:
                # RAG 检索不足时，尝试关键词匹配兜底回答
                fallback_reply = self._keyword_fallback(message, intent)
                if fallback_reply:
                    reply = fallback_reply
                else:
                    reply = check["message"]
                # C4 风控联动：即使兜底回复也附加风险提示
                if is_sensitive and risk_context.get("risk_level"):
                    risk_reply = self._get_risk_aware_reply(risk_context)
                    if risk_reply:
                        reply = risk_reply + "\n\n---\n\n" + reply
                # C5 反馈闭环
                if detected_signal:
                    feedback_reply = self._get_signal_feedback_reply(detected_signal)
                    if feedback_reply:
                        reply = feedback_reply + "\n\n---\n\n" + reply
                sources = []
            else:
                # 增强生成（注入跨 session 记忆）
                llm_response = await self._generate_with_context(
                    message, rag_results, history,
                    user_profile=user_profile,
                    historical_preferences=historical_preferences,
                    historical_conversations=historical_conversations,
                )

                # 解析 LLM 返回的 JSON
                try:
                    llm_data = json.loads(llm_response)
                    reply = llm_data.get("reply", llm_response)
                    # 如果 LLM 返回了 sources，使用 LLM 的 sources
                    if llm_data.get("sources"):
                        sources = [SourceReference(
                            title=s,
                            source_file="",
                            chunk_index=0,
                            score=0.0,
                            content_snippet=""
                        ) for s in llm_data["sources"]]
                    else:
                        sources = self._build_sources(rag_results)
                except (json.JSONDecodeError, AttributeError):
                    # 解析失败，使用原始响应
                    reply = llm_response
                    sources = self._build_sources(rag_results)

                # ── C4 风控联动：敏感操作附加风险提示 ──
                if is_sensitive and risk_context.get("risk_level"):
                    risk_reply = self._get_risk_aware_reply(risk_context)
                    if risk_reply:
                        reply = risk_reply + "\n\n---\n\n" + reply
                        logger.info(
                            "C4联动: 客户%s 敏感操作(%s) 附加风险提示 | level=%s",
                            user_id, intent, risk_context.get("risk_level"),
                        )

                # C5 反馈闭环：检测到信号后附加安抚话术
                if detected_signal:
                    feedback_reply = self._get_signal_feedback_reply(detected_signal)
                    if feedback_reply:
                        reply = feedback_reply + "\n\n---\n\n" + reply

                # 安全审核
                safety_result = await self.safety.check_content(llm_response)
                if not safety_result.passed:
                    # C4 风控联动：安全审核不通过时，附加风险提示
                    if is_sensitive and risk_context.get("risk_level"):
                        risk_reply = self._get_risk_aware_reply(risk_context)
                        if risk_reply:
                            reply = risk_reply + "\n\n⚠️ 该问题需要人工客服进一步确认。请拨打客服热线400-XXX-XXXX。"
                        else:
                            reply = "抱歉，该问题需要人工客服进一步确认。请拨打客服热线400-XXX-XXXX。"
                    else:
                        reply = "抱歉，该问题需要人工客服进一步确认。请拨打客服热线400-XXX-XXXX。"

                # ── 强制风险提示（金融合规要求：涉及产品/收益时必须附加风险声明）──
                if intent in ("product_inquiry", "faq"):
                    reply = self._append_risk_disclaimer(reply, intent)
        # 4. 更新短期记忆
        await self.memory.save_message(session_id, "user", message)
        await self.memory.save_message(session_id, "assistant", reply)

        # 5. 长期归档由统一聊天入口在回复成功后统一处理
        return CustomerChatResponse(
            reply=reply,
            sources=sources,
            session_id=session_id,
            intent=intent,
            confidence=intent_confidence,
        )

    async def _query_risk_context(self, user_id: int) -> dict:
        """
        C4 风控联动：查询客户风险上下文

        数据来源（按优先级）：
        1. Redis cs_risk_ctx:{user_id} — C4事件频道实时写入的上下文
        2. MySQL fin_customer_profile.risk_flag — 画像风险标记
        3. MySQL fin_risk_alert — 近期预警统计

        Returns:
            {risk_level: "high"|"medium"|"low"|None, alert_count: int, has_recent_alert: bool}
        """
        result = {"risk_level": None, "alert_count": 0, "has_recent_alert": False}

        # 1. 查询 Redis C4 上下文
        try:
            from app.config.database import get_redis
            import json
            r = await get_redis()
            ctx = await r.get(f"cs_risk_ctx:{user_id}")
            if ctx:
                ctx_data = json.loads(ctx)
                if ctx_data.get("has_alert"):
                    result["has_recent_alert"] = True
                    logger.info(f"C4联动: 客户{user_id} Redis风险上下文命中")
        except Exception as e:
            logger.debug(f"C4联动 Redis查询失败(非阻断): {e}")

        # 2. 查询画像风险标记
        try:
            from sqlalchemy import text
            row = await self.db.execute(
                text("SELECT risk_flag FROM fin_customer_profile WHERE customer_id = :cid"),
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
            logger.debug(f"C4联动 画像查询失败(非阻断): {e}")

        # 3. 查询近期预警数量
        try:
            from sqlalchemy import text
            from datetime import timedelta
            thirty_days_ago = datetime.now() - timedelta(days=30)
            row = await self.db.execute(
                text(
                    "SELECT COUNT(*) FROM fin_risk_alert "
                    "WHERE customer_id = :cid AND created_at >= :since"
                ),
                {"cid": user_id, "since": thirty_days_ago},
            )
            count = row.scalar() or 0
            result["alert_count"] = count
            if count > 0:
                result["has_recent_alert"] = True
                # 根据预警数量调整等级
                if count >= 3 and result["risk_level"] != "high":
                    result["risk_level"] = "high"
                elif count >= 1 and result["risk_level"] is None:
                    result["risk_level"] = "medium"
        except Exception as e:
            logger.debug(f"C4联动 预警统计失败(非阻断): {e}")

        return result

    @staticmethod
    def _is_sensitive_query(message: str) -> bool:
        """C4 联动：检测用户消息是否涉及敏感金融操作"""
        import re
        sensitive_patterns = [
            r'大额.*(?:转账|转出|汇款)',
            r'(?:转账|转出|汇款).*大额',
            r'(?:大额|大量).*(?:赎回|取出|提现)',
            r'(?:赎回|取出|提现).*(?:大额|大量)',
            r'(?:大额|大量).*(?:申购|买入|购买)',
            r'想.*(?:转账|转出|汇款)',
            r'怎么.*(?:转账|汇款|大额)',
        ]
        for pattern in sensitive_patterns:
            if re.search(pattern, message):
                return True
        return False

    def _get_risk_aware_reply(self, risk_context: dict) -> str:
        """C4 联动：根据风险等级生成风控提示"""
        risk_level = risk_context.get("risk_level")
        if risk_level and risk_level in self.RISK_AWARE_TEMPLATES:
            return self.RISK_AWARE_TEMPLATES[risk_level]
        return ""

    # ═══════════════════════════════════════════════════════════
    # C5 反向联动：客服→风控 信号检测层
    # ═══════════════════════════════════════════════════════════

    async def _detect_risk_signals(
        self, session_id: str, user_id: int, message: str, history: list[dict]
    ) -> Optional[RiskSignal]:
        """
        C5 反向联动：三级风控信号检测

        L1: 关键词规则（<1ms）
        L2: 行为模式 — Redis 频率计数（<5ms）
        L3: LLM 辅助意图分类（~500ms，仅在 L1/L2 不确定时触发）

        去重：同客户同信号类型在 dedup_window 内只上报一次。

        Returns:
            检测到的最高优先级信号，未检测到返回 None
        """
        risk_signal_cfg = self.settings.risk_signal

        # ── L1: 关键词规则检测 ──
        l1_signals = detect_l1_signals(message)

        # ── L2: 行为模式检测（Redis 频率计数）──
        l2_triggered = False
        l2_signal = await self._check_l2_behavior_pattern(
            user_id, l1_signals, risk_signal_cfg
        )
        if l2_signal:
            l2_triggered = True
            l1_signals.append(l2_signal)

        # 选出最高优先级信号
        best_signal = self._pick_best_signal(l1_signals)

        # ── 去重检查 ──
        if best_signal:
            is_dup = await self._check_dedup(user_id, best_signal, risk_signal_cfg)
            if is_dup:
                logger.debug(
                    "C5信号去重命中 | user=%s | signal=%s", user_id, best_signal.signal_type
                )
                return None

        # ── L3: LLM 辅助检测（仅在需要时触发）──
        need_l3 = should_trigger_l3_detection(l1_signals, l2_triggered)
        if need_l3:
            l3_signal = await self._l3_llm_detection(message, history, user_id)
            if l3_signal:
                # L3 结果与 L1 合并，取最优
                if best_signal is None or l3_signal.confidence > best_signal.confidence:
                    best_signal = l3_signal
                # L3 去重
                if best_signal is l3_signal:
                    is_dup = await self._check_dedup(user_id, best_signal, risk_signal_cfg)
                    if is_dup:
                        return None

        # ── 上报决策 ──
        if best_signal is None:
            return None

        # low 级信号根据配置决定是否上报
        if best_signal.signal_level == "low" and not risk_signal_cfg.report_low_level:
            logger.info(
                "C5信号仅记录日志(不上报) | user=%s | signal=%s | confidence=%.2f",
                user_id, best_signal.signal_type, best_signal.confidence,
            )
            return None

        # 置信度阈值检查
        threshold = (
            risk_signal_cfg.l3_confidence_threshold
            if best_signal.confidence >= risk_signal_cfg.l1_confidence_threshold
            else risk_signal_cfg.l1_confidence_threshold
        )
        if best_signal.confidence < threshold:
            logger.info(
                "C5信号置信度不足(不上报) | user=%s | signal=%s | confidence=%.2f < threshold=%.2f",
                user_id, best_signal.signal_type, best_signal.confidence, threshold,
            )
            return None

        # ── 发布 C5 事件 ──
        await self._publish_c5_event(session_id, user_id, best_signal)

        # ── 写入去重标记 ──
        await self._write_dedup(user_id, best_signal, risk_signal_cfg)

        logger.info(
            "C5信号已上报 | user=%s | signal=%s | level=%s | confidence=%.2f",
            user_id, best_signal.signal_type, best_signal.signal_level, best_signal.confidence,
        )
        return best_signal

    async def _check_l2_behavior_pattern(
        self, user_id: int, l1_signals: list[RiskSignal], cfg
    ) -> Optional[RiskSignal]:
        """
        L2 行为模式检测：通过 Redis 频率计数器检测异常行为模式

        规则：同一客户在 time_window 内触发 >= threshold 次 L1 信号 → 升级为 high
        """
        if not l1_signals:
            return None

        try:
            from app.config.database import get_redis
            r = await get_redis()
            counter_key = f"cs_signal_count:{user_id}"
            count = await r.incr(counter_key)
            if count == 1:
                await r.expire(counter_key, cfg.frequent_signal_window_minutes * 60)

            if count >= cfg.frequent_signal_threshold:
                logger.info(
                    "C5 L2行为模式触发 | user=%s | count=%s >= threshold=%s",
                    user_id, count, cfg.frequent_signal_threshold,
                )
                return RiskSignal(
                    signal_type="behavior_change",
                    signal_level="high",
                    confidence=0.8,
                    keywords_hit=[],
                    evidence={
                        "pattern": "frequent_sensitive_signals",
                        "count": count,
                        "window_minutes": cfg.frequent_signal_window_minutes,
                    },
                )
        except Exception as e:
            logger.warning("C5 L2行为模式检测失败(非阻断): %s", e)

        return None

    async def _l3_llm_detection(
        self, message: str, history: list[dict], user_id: int
    ) -> Optional[RiskSignal]:
        """
        L3 LLM 辅助检测：使用现有大模型对对话上下文做意图分类

        将最近几轮对话 + 当前消息送入 LLM，判断是否存在风控信号。
        仅在 L1/L2 不确定时触发，避免不必要的延迟。
        """
        try:
            # 构建对话上下文
            recent_history = history[-6:]  # 最近3轮对话
            conversation_parts = []
            for msg in recent_history:
                role_label = "客户" if msg.get("role") == "user" else "客服"
                content = (msg.get("content") or "")[:200]
                conversation_parts.append(f"{role_label}: {content}")
            conversation_parts.append(f"客户: {message[:200]}")
            conversation_text = "\n".join(conversation_parts)

            prompt = LLM_SIGNAL_CLASSIFICATION_PROMPT.replace(
                "{conversation}", conversation_text
            )
            messages = [{"role": "user", "content": prompt}]

            reply = await self.llm.chat_with_fallback(
                messages=messages, temperature=0.1, max_tokens=200
            )

            # 解析 LLM 返回的 JSON
            result = self._extract_json_from_text(reply)
            if not result:
                return None

            if not result.get("has_signal"):
                logger.info("C5 L3检测: 未发现信号 | user=%s", user_id)
                return None

            signal_type = result.get("signal_type")
            confidence = float(result.get("confidence", 0.5))
            reason = result.get("reason", "")

            if not signal_type or signal_type == "null":
                return None

            # 根据 LLM 置信度确定信号等级
            if confidence >= 0.85:
                signal_level = "high"
            elif confidence >= 0.65:
                signal_level = "medium"
            else:
                signal_level = "low"

            logger.info(
                "C5 L3 LLM检测命中 | user=%s | signal=%s | level=%s | confidence=%.2f | reason=%s",
                user_id, signal_type, signal_level, confidence, reason[:80],
            )
            return RiskSignal(
                signal_type=signal_type,
                signal_level=signal_level,
                confidence=confidence,
                keywords_hit=[],
                evidence={
                    "source": "llm_l3",
                    "reason": reason[:200],
                    "message": message[:200],
                },
            )

        except Exception as e:
            logger.warning("C5 L3 LLM检测失败(非阻断): %s", e)
            return None

    async def _check_dedup(
        self, user_id: int, signal: RiskSignal, cfg
    ) -> bool:
        """检查去重：同客户同信号类型在 dedup_window 内是否已上报"""
        try:
            from app.config.database import get_redis
            r = await get_redis()
            dedup_key = f"cs_signal_dedup:{user_id}:{signal.signal_type}"
            exists = await r.exists(dedup_key)
            return exists > 0
        except Exception as e:
            logger.warning("C5去重检查失败(非阻断): %s", e)
            return False

    async def _write_dedup(
        self, user_id: int, signal: RiskSignal, cfg
    ) -> None:
        """写入去重标记"""
        try:
            from app.config.database import get_redis
            r = await get_redis()
            dedup_key = f"cs_signal_dedup:{user_id}:{signal.signal_type}"
            await r.set(dedup_key, "1", ex=cfg.dedup_window)
        except Exception as e:
            logger.warning("C5去重标记写入失败(非阻断): %s", e)

    async def _publish_c5_event(
        self, session_id: str, user_id: int, signal: RiskSignal
    ) -> None:
        """发布 C5 事件到 event_bus"""
        try:
            from app.service.event_bus import publish_event, EVENT_C5_RISK_FROM_CUSTOMER
            payload = {
                "source": "customer_agent",
                "customer_id": user_id,
                "session_id": session_id,
                "signal_type": signal.signal_type,
                "signal_level": signal.signal_level,
                "confidence": signal.confidence,
                "evidence": {
                    "message": signal.evidence.get("message", "")[:200],
                    "keywords_hit": signal.keywords_hit,
                    "source": signal.evidence.get("source", "l1_l2"),
                },
                "timestamp": datetime.now().isoformat(),
            }
            await publish_event(EVENT_C5_RISK_FROM_CUSTOMER, payload)
            logger.info(
                "C5事件已发布 | user=%s | signal=%s | session=%s",
                user_id, signal.signal_type, session_id,
            )
        except Exception as e:
            logger.warning("C5事件发布失败(非阻断): %s", e)

    @staticmethod
    def _pick_best_signal(signals: list[RiskSignal]) -> Optional[RiskSignal]:
        """从信号列表中选出最高优先级的信号"""
        if not signals:
            return None
        level_order = {"high": 3, "medium": 2, "low": 1}
        return max(signals, key=lambda s: (level_order.get(s.signal_level, 0), s.confidence))

    def _get_signal_feedback_reply(self, signal: RiskSignal) -> str:
        """
        C5 反馈闭环：根据检测到的信号生成安抚/告知话术

        风控Agent处理后会写入 Redis 反馈，此处先根据信号类型给出初步安抚。
        """
        feedback_templates = {
            "account_compromise": (
                "🔒 **安全提示**：我们已注意到您的账户安全异常，系统已自动上报安全团队。"
                "为保障您的资金安全，建议您立即修改登录密码和交易密码。"
                "如需紧急冻结账户，请拨打客服热线 400-XXX-XXXX。"
            ),
            "social_engineering": (
                "⚠️ **安全提醒**：为保障您的信息安全，请勿向他人透露账户密码、验证码等敏感信息。"
                "如有任何疑问，请通过官方渠道联系我们。"
            ),
            "abnormal_intent": (
                "📋 **温馨提示**：大额交易可能需要额外的身份验证流程。"
                "为保障您的资金安全，系统可能会对本次操作进行安全审核。感谢您的理解与配合。"
            ),
            "behavior_change": (
                "📋 **温馨提示**：系统检测到您的账户操作模式有所变化。"
                "为保障您的资金安全，部分操作可能需要额外的安全验证。如有疑问请联系客服。"
            ),
            "identity_failure": (
                "🔐 **身份验证提示**：检测到多次身份验证未通过。"
                "为保障您的账户安全，建议您通过官方APP重新进行身份认证，或携带有效证件前往柜台办理。"
            ),
        }
        template = feedback_templates.get(signal.signal_type, "")
        if not template:
            return ""

        # 尝试读取风控Agent的反馈（如果已处理完成）
        # 此处为同步读取，实际反馈可能在下一条消息时才写入
        return template

    async def _query_c5_feedback(self, session_id: str, user_id: int) -> Optional[dict]:
        """
        查询风控Agent对C5信号的处理反馈

        从 Redis cs_risk_feedback:{session_id}:{user_id} 读取
        """
        try:
            from app.config.database import get_redis
            r = await get_redis()
            feedback_key = f"cs_risk_feedback:{session_id}:{user_id}"
            data = await r.get(feedback_key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.debug("C5反馈查询失败(非阻断): %s", e)
        return None

    async def _handle_chitchat(self, message: str, history: list[dict]) -> str:
        """处理闲聊"""
        system_prompt = _load_chitchat_prompt()

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-4:])  # 最近2轮对话
        messages.append({"role": "user", "content": message})

        try:
            reply = await self.llm.chat_with_fallback(messages=messages, temperature=0.7, max_tokens=200)
            return reply
        except Exception as e:
            logger.error(f"闲聊回复失败: {e}")
            return "您好！我是智能财富管家AI客服，请问有什么可以帮您的？"

    async def _generate_with_context(
        self,
        message: str,
        rag_results: list[dict],
        history: list[dict],
        user_profile: str = "",
        historical_preferences: str = "",
        historical_conversations: str = "",
    ) -> str:
        """基于 RAG 上下文生成回答，输出纯 JSON 格式"""
        import json
        import re

        # 加载 System Prompt（使用缓存）
        system_prompt = _load_customer_prompt()

        # 拼接参考资料
        context_docs = []
        for i, r in enumerate(rag_results):
            content = r.get("content", "")
            source_info = r.get("source_info", {})
            title = source_info.get("title", "未知")
            context_docs.append(f"[资料{i+1}] 来源：《{title}》\n{content}")
        context_text = "\n\n".join(context_docs)

        # 拼接对话历史
        history_text = ""
        for msg in history[-4:]:
            role = "客户" if msg["role"] == "user" else "客服"
            history_text += f"{role}：{msg['content']}\n"

        # 组装完整 Prompt（使用安全替换，避免用户输入中的 { } 导致 KeyError）
        full_prompt = system_prompt.replace("{context_documents}", context_text)
        full_prompt = full_prompt.replace("{chat_history}", history_text)
        full_prompt = full_prompt.replace("{user_question}", message)
        # 注入跨 session 记忆（画像摘要 + 历史偏好 + 近期对话），无数据时为空字符串
        full_prompt = full_prompt.replace("{user_profile}", user_profile or "暂无客户画像信息")
        full_prompt = full_prompt.replace("{historical_preferences}", historical_preferences or "暂无历史偏好记录")
        full_prompt = full_prompt.replace("{historical_conversations}", historical_conversations or "")

        messages = [{"role": "user", "content": full_prompt}]

        try:
            reply = await self.llm.chat_with_fallback(messages=messages, temperature=0.3, max_tokens=1024)

            # 尝试解析 LLM 返回的 JSON
            json_result = self._extract_json_from_text(reply)

            if json_result:
                # 确保是纯 JSON 字符串输出
                return json.dumps(json_result, ensure_ascii=False)
            else:
                # 解析失败，构造兜底 JSON
                logger.warning(f"LLM 返回内容无法解析为 JSON，使用兜底格式 | reply={reply[:100]}...")
                fallback_json = {
                    "reply": reply if reply else "抱歉，系统繁忙，请稍后重试。",
                    "sources": [],
                    "need_human": False,
                    "confidence": 0.5
                }
                return json.dumps(fallback_json, ensure_ascii=False)

        except Exception as e:
            logger.error(f"LLM 生成失败: {e}")
            error_json = {
                "reply": "抱歉，系统繁忙，请稍后重试。",
                "sources": [],
                "need_human": True,
                "confidence": 0.0
            }
            return json.dumps(error_json, ensure_ascii=False)

    def _extract_json_from_text(self, text: str) -> Optional[dict]:
        """从 LLM 返回的文本中提取 JSON 对象（含推理文本剥离）"""
        import json
        import re

        if not text:
            return None

        text = text.strip()

        # 0. 剥离推理/思考前缀（如"我们被要求..."、"思考过程：..."）
        text = re.sub(r'^(?:思考过程|分析过程|推理过程|思考|分析|推理|让我分析|我来分析)[^\{}\n]*[:：]?\s*', '', text)
        text = re.sub(r'^(?:我们被要求|我需要|根据要求)[^\{}\n]*\n+', '', text)
        text = text.strip()

        # 1. 去除可能的 markdown 代码块包裹
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        text = text.strip()

        # 2. 尝试直接解析
        if text.startswith('{'):
            try:
                result = json.loads(text)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        # 3. 从文本中提取 JSON 对象
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            try:
                result = json.loads(json_match.group())
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        # 4. 尝试提取关键字段
        reply_match = re.search(r'"reply"\s*:\s*"([^"]*)"', text)
        if reply_match:
            return {
                "reply": reply_match.group(1),
                "sources": [],
                "need_human": False,
                "confidence": 0.5
            }

        return None

    @staticmethod
    def _append_risk_disclaimer(reply: str, intent: str) -> str:
        """
        金融合规要求：涉及产品/收益的回答必须附加风险提示。

        根据意图类型附加不同的风险声明，确保符合资管新规要求。
        """
        # 如果回复中已经包含风险提示关键词，不重复添加
        if any(kw in reply for kw in ["风险提示", "投资有风险", "不构成投资建议", "过往业绩"]):
            return reply

        disclaimers = {
            "product_inquiry": (
                "\n\n---\n⚠️ **风险提示**：理财非存款，产品有风险，投资需谨慎。"
                "以上信息仅供参考，不构成投资建议。具体产品详情请查阅官方产品说明书，"
                "并根据自身风险承受能力做出投资决策。"
            ),
            "faq": (
                "\n\n---\n⚠️ **温馨提示**：以上为通用业务规则说明，具体以产品合同和"
                "基金公司公告为准。如有疑问，建议咨询专业理财顾问或拨打客服热线。"
            ),
        }
        disclaimer = disclaimers.get(intent, "")
        if disclaimer:
            return reply + disclaimer
        return reply

    @staticmethod
    def _keyword_fallback(message: str, intent: str) -> Optional[str]:
        """
        RAG 检索不可用时的关键词匹配兜底回答。

        基于金融领域常见关键词提供预设回复，确保用户在系统降级时
        仍能获得基本服务，而非仅看到"请联系人工"。

        Returns:
            匹配到的兜底回复，无匹配时返回 None（走原有 fallback 逻辑）。
        """
        msg_lower = message.lower()

        # FAQ 类关键词
        faq_patterns = {
            "申购|买入|购买|怎么买": "基金申购通常在交易日15:00前提交，按当日净值确认份额；15:00后提交则按下一交易日净值确认。申购确认后T+1日可查看持仓。",
            "赎回|卖出|怎么卖": "基金赎回通常在交易日15:00前提交，按当日净值计算；赎回到账时间因产品类型不同：货币基金T+1，债券基金T+2-3，股票基金T+3-5个工作日。",
            "手续费|费用|费率": "不同产品费率不同。货币基金通常免申购费，债券基金管理费约0.3%-0.6%，股票基金管理费约1.0%-1.5%。具体请查看产品详情页。",
            "开户|注册": "您可以通过XX证券APP在线开户，准备好身份证和银行卡，按指引完成身份认证和风险测评即可。",
            "风险测评|风险评估|风评": "风险测评是投资者适当性管理的重要环节，您需要完成16道风险评估问卷。测评结果分为C1-C5五个等级，有效期一年。",
        }

        # 产品类关键词
        product_patterns = {
            "稳健|低风险|保本|安全": "稳健型产品包括货币基金（R1）和债券基金（R2），风险较低。但请注意：任何理财产品都不承诺保本保息，投资需谨慎。",
            "收益|收益率|回报": "不同风险等级的产品预期收益不同：R1货币基金约2%-3%，R2债券基金约3%-5%，R3混合基金约5%-8%，R4+股票基金可能有更高收益但伴随更大风险。历史收益不代表未来表现。",
            "推荐|建议|适合": "产品推荐需基于您的风险测评结果。建议您先完成风险测评问卷，系统会根据您的风险等级（C1-C5）自动推荐适当性匹配的产品。",
        }

        # 政策类关键词
        policy_patterns = {
            "资管新规|适当性|合规": "根据《关于规范金融机构资产管理业务的指导意见》（资管新规），理财产品不得承诺保本保收益，投资者应根据自身风险承受能力选择适当的产品。",
            "反洗钱|AML|可疑": "根据反洗钱法规，金融机构需对客户身份进行识别，并对大额和可疑交易进行监测和报告。这是保障金融安全的重要措施。",
        }

        # 按意图选择匹配规则
        if intent in ("faq", "chitchat"):
            patterns = faq_patterns
        elif intent == "product_inquiry":
            patterns = {**product_patterns, **faq_patterns}
        elif intent == "policy_interpretation":
            patterns = policy_patterns
        else:
            patterns = {**faq_patterns, **product_patterns, **policy_patterns}

        import re
        for pattern, response in patterns.items():
            if re.search(pattern, msg_lower):
                logger.info(f"关键词兜底命中 | pattern={pattern[:20]}...")
                return response + "\n\n（提示：当前知识库检索暂不可用，以上为通用回复，如需详细信息请联系人工客服。）"

        return None

    def _build_sources(self, rag_results: list[dict]) -> list[SourceReference]:
        """构建来源引用列表"""
        sources = []
        for r in rag_results:
            source_info = r.get("source_info", {})
            metadata = r.get("metadata", {})

            # 智能截断 content_snippet，避免在词语中间截断
            content = r.get("content", "")
            if len(content) > 100:
                # 截取前 100 个字符
                snippet = content[:100]
                # 找到最后一个完整的词语边界（句号、逗号、空格、换行等）
                for sep in ['。', '，', '、', '；', '！', '？', '\n', ' ', '.', ',']:
                    last_sep = snippet.rfind(sep)
                    if last_sep > 50:  # 至少保留 50 个字符
                        snippet = snippet[:last_sep + 1]
                        break
                else:
                    # 如果没找到合适的分隔符，就保持 100 字符
                    snippet = snippet
            else:
                snippet = content

            sources.append(SourceReference(
                title=source_info.get("title", "未知"),
                source_file=source_info.get("source_file", ""),
                chunk_index=metadata.get("chunk_index", 0),
                score=r.get("score", 0),
                content_snippet=snippet,
            ))
        return sources


def get_customer_service_agent(db: AsyncSession) -> CustomerServiceAgent:
    """获取客服 Agent 实例"""
    return CustomerServiceAgent(db)
