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
from app.tool.llm_tool import get_llm_tool
from app.utils.logger import get_logger

logger = get_logger("service.agent")


class CustomerServiceAgent:
    """智能客服Agent核心类"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.intent_service = get_intent_service()
        self.rag_service = get_rag_service(db)
        self.memory = get_memory_service(db)
        self.safety = get_safety_service()
        self.llm = get_llm_tool()

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

        # 1. 加载短期记忆
        history = await self.memory.get_history(session_id)

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
                reply = check["message"]
                sources = []
            else:
                # 增强生成
                llm_response = await self._generate_with_context(message, rag_results, history)

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
        # 加载闲聊回复 Prompt
        prompt_path = Path(__file__).parent.parent / "prompts" / "chitchat_reply.txt"
        if prompt_path.exists():
            system_prompt = prompt_path.read_text(encoding="utf-8")
        else:
            system_prompt = "你是XX科技智能财富管家的AI客服助手，请友好地回复用户，并引导回金融业务话题。"

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-4:])  # 最近2轮对话
        messages.append({"role": "user", "content": message})

        try:
            reply = await self.llm.chat(messages=messages, temperature=0.7, max_tokens=200)
            return reply
        except Exception as e:
            logger.error(f"闲聊回复失败: {e}")
            return "您好！我是智能财富管家AI客服，请问有什么可以帮您的？"

    async def _generate_with_context(
        self, message: str, rag_results: list[dict], history: list[dict]
    ) -> str:
        """基于 RAG 上下文生成回答，输出纯 JSON 格式"""
        import json
        import re

        # 加载 System Prompt
        prompt_path = Path(__file__).parent.parent / "prompts" / "customer_system.txt"
        if prompt_path.exists():
            system_prompt = prompt_path.read_text(encoding="utf-8")
        else:
            system_prompt = "你是XX科技智能财富管家的AI客服助手，请基于参考资料回答客户问题。"

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

        # 组装完整 Prompt
        full_prompt = system_prompt.format(
            context_documents=context_text,
            chat_history=history_text,
            user_question=message,
        )

        messages = [{"role": "user", "content": full_prompt}]

        try:
            reply = await self.llm.chat(messages=messages, temperature=0.3, max_tokens=1024)

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
