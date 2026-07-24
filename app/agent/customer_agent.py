"""
Agent Service — 客服Agent核心编排逻辑
完整流程：会话管理 → 意图路由 → 记忆召回 → RAG检索 → 结果组装 → 安全审核 → 归档
"""

from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.model.schemas import CustomerChatResponse, SourceReference
from app.service.intent_service import get_intent_service
from app.service.rag_service import get_rag_service
from app.service.memory_service import get_memory_service
from app.service.safety_service import get_safety_service
from app.service.memory_recall_service import get_memory_recall_service
from app.tool.llm_tool import get_llm_tool
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
    """智能客服Agent核心类"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.intent_service = get_intent_service()
        self.rag_service = get_rag_service(db)
        self.memory = get_memory_service(db)
        self.safety = get_safety_service()
        self.llm = get_llm_tool()
        self.memory_recall = get_memory_recall_service()

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

        # 3. 根据意图执行对应逻辑
        if intent == "transfer_human":
            reply = "正在为您转接人工客服，请稍候..."
            sources = []

        elif intent == "chitchat":
            reply = await self._handle_chitchat(message, history)
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
                    sources = []
                else:
                    reply = check["message"]
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
                import json
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

                # 安全审核
                safety_result = await self.safety.check_content(llm_response)
                if not safety_result.passed:
                    reply = "抱歉，该问题需要人工客服进一步确认。请拨打客服热线400-XXX-XXXX。"

                # ── 强制风险提示（金融合规要求：涉及产品/收益时必须附加风险声明）──
                if intent in ("product_inquiry", "faq"):
                    reply = self._append_risk_disclaimer(reply, intent)
        # 4. 更新短期记忆
        await self.memory.save_message(session_id, "user", message)
        await self.memory.save_message(session_id, "assistant", reply)

        # 5. 异步归档
        self.memory.archive_conversation_bg(
            session_id=session_id,
            user_id=user_id,
            agent_type="customer_service",
            role="user",
            content=message,
        )
        self.memory.archive_conversation_bg(
            session_id=session_id,
            user_id=user_id,
            agent_type="customer_service",
            role="assistant",
            content=reply,
        )

        return CustomerChatResponse(
            reply=reply,
            sources=sources,
            session_id=session_id,
            intent=intent,
            confidence=intent_confidence,
        )

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
        """从 LLM 返回的文本中提取 JSON 对象"""
        import json
        import re

        if not text:
            return None

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
