"""
投顾 AdvisorAgent — LLM 驱动的多工具统一投顾入口

核心理念：决策者从「开发者的 if/elif」变为「LLM 大模型」。

Agent 拥有一个工具箱：
  - profile_tool         → 查客户风险画像（四维度 + 熔断）
  - compare_customers    → 对比两个客户的画像、持仓、行业偏好差异
  - analysis_holdings    → 持仓分析（持仓分布、行业集中度、盈亏状态）
  - recommend_products   → 产品推荐打分排序
  - asset_allocation     → 资产配置建议
  - graphrag_search      → 知识图谱 + 向量文档检索

LLM 根据用户自然语言自动决定：
  调用哪个工具、按什么顺序调用、如何组合结果生成回复。

这是 ProfileAgent 的同款模式 — 只是工具箱里从 1 个工具扩展到了 6 个。
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from app.agent.base_agent import BaseAgent
from app.config.settings import get_settings
from app.tool.profile_tool import ProfileTool
from app.tool.holding_tool import HoldingTool
from app.tool.comparison_tool import ComparisonTool
from app.tool.graphrag_tool import graphrag_tool
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ══════════════════════════════════════════════════════════════════
# JSON 序列化辅助
# ══════════════════════════════════════════════════════════════════


def _json_default(obj):
    """JSON 序列化辅助：正确处理 Pydantic 模型"""
    if hasattr(obj, 'model_dump'):
        return obj.model_dump()
    return str(obj)


def _level_to_name_static(level: str) -> str:
    """风险等级代码转中文名称（静态辅助函数）"""
    mapping = {"C1": "保守型", "C2": "稳健型", "C3": "平衡型", "C4": "进取型", "C5": "激进型"}
    return mapping.get(level, level)


# ══════════════════════════════════════════════════════════════════
# System Prompt — 投顾分析师的"人设"
# ══════════════════════════════════════════════════════════════════

ADVISOR_SYSTEM_PROMPT = """# 角色
你是**智能财富管理投顾分析师**，服务于某大型券商的财富管理中心。
你的工作是为理财顾问提供客户画像解读、产品推荐、资产配置建议和知识检索服务。

# 核心能力 & 可用工具

你有**七个**工具可以调用，根据用户意图**自行决定**调用哪些、按什么顺序调用：

| 工具名 | 用途 | 何时调用 |
|--------|------|----------|
| `profile_tool` | 查询客户风险画像（四维度得分、C1-C5等级、熔断规则） | 用户提到客户、画像、风险等级、研判、评估 |
| `smart_recommend` | **一键智能推荐**：自动查画像 + 产品推荐 + 资产配置建议，一步到位 | 用户问"推荐产品""适合什么产品""买什么好""有什么推荐" |
| `compare_customers` | 对比两个客户的画像、持仓、行业偏好差异 | 用户要求对比两个客户、看有什么不同 |
| `analysis_holdings` | 分析客户持仓分布、行业集中度、盈亏状态 | 用户要求分析持仓、看集中度、行业分布 |
| `recommend_products` | 根据客户ID推荐匹配的产品列表 | 用户只需要推荐产品、已明确不需要画像和配置 |
| `asset_allocation` | 给出该客户的资产配置比例建议 | 用户只要求资产配置、仓位建议、比例分配 |
| `graphrag_search` | 检索知识图谱和文档库（行业/产品/客户关联关系） | 用户问行业分布、产品关联、知识性问题 |

# 工具调用策略

1. **一键推荐优先**：如果用户问"这个客户适合什么产品""有什么推荐""推荐几款产品"，
   **直接调 smart_recommend**，该工具内部已完成画像查询+产品推荐+资产配置，
   不需要先调 profile_tool 再调 recommend_products，一次调用就够了。
2. **先查后推（仅当不适用 smart_recommend 时）**：如果用户既要看画像细节又要推荐产品，
   且 smart_recommend 返回的画像摘要不够详细时，可调 profile_tool 补充。
3. **多工具组合**：用户可能一次提出复合需求，如"帮我看看张三的画像，推荐几款产品，
   再查查新能源行业有什么热门基金"——使用 smart_recommend + graphrag_search 即可。
4. **独立调用**：如果用户只想要资产配置，直接调 asset_allocation，不需要先查画像。
5. **持仓分析**：如果用户要求看持仓、行业集中度、盈亏状态，调 analysis_holdings。
   该工具会综合 MySQL 持仓明细和 Neo4j 行业关系图谱，返回完整持仓分析结果。
6. **客户对比**：如果用户要求对比两个客户（如"比较张三和李四"），调 compare_customers。
   该工具接收两个客户ID，返回画像差异、共同持仓、行业偏好对比等结构化报告。
7. **知识类问题**：如果用户问的是知识性问题（如"什么是R3风险等级"、"新能源行业前景如何"），
   只调 graphrag_search，不要调其他工具。

# 输出规范

回答时请使用 Markdown 格式。严格遵循以下结构，**不要自创章节名称**：

## 回复结构（按优先级排列）

**1. 状态提示（有异常时才出现，无异常则跳过）**
- 用一段简短引用块（`>`）概括当前请求的处理状态
- 如果画像查询正常 → 不展示此块，直接进入产品推荐
- 如果画像不存在 → "该客户暂未完成风险测评，系统已按最低风险等级（C1保守型）匹配产品。建议引导客户完成测评以获得更精准的推荐。"
- 如果画像查询出错 → "客户画像暂时无法获取，已基于历史数据完成产品匹配，推荐结果供参考。"
- **禁止在此处暴露工具返回的原始错误信息**（如错误码、异常堆栈等）
- 字数控制在 80 字以内

**2. 风控预警（有预警时才出现，无预警则完全跳过此章节）**
- 仅当 smart_recommend 返回 risk_alerts.alert_level 为 high/medium 时才展示
- 无预警时**不要**展示"✅ 无风控预警"之类的段落

**3. 客户风险画像（可选）**
- 展示基本信息 + 风险等级（C1-C5）+ 风险评分
- 如有熔断告警或 warnings，务必突出提醒

**4. 产品推荐**
- 推荐产品列表，含风险等级、预期收益、匹配度、推荐理由
- 优先使用表格格式，便于理财顾问快速对比
- 如有风控限制，必须说明推荐范围已被约束

**5. 资产配置建议（可选）**
- 各资产类型配比百分比 + 配置逻辑简述

**6. 客户对比分析 / 持仓分析 / 知识检索结果（按需出现）**

**7. 风险提示（必须出现，固定章节）**
- 所有包含产品推荐的回答**必须**在末尾添加风险提示
- 固定文案："> ⚠️ **风险提示**：投资有风险，入市需谨慎。以上推荐基于当前画像和历史数据生成，不构成投资建议。过往业绩不代表未来表现，请根据自身风险承受能力审慎决策。如有疑问，请咨询持牌理财顾问。"

# 语言风格
- **精炼优先**：用最少的字传达最多的信息，避免铺垫和过度修饰
- 面向理财顾问，专业但不晦涩，使用金融行业通用术语
- **数据驱动**：每个结论必须有数据支撑，引用具体数字而非模糊描述
- 风险意识：熔断告警和风控预警信息必须置于推荐内容之前
- 语气专业、冷静、客观，不使用感叹号或过度情绪化表达

# 禁止事项
- 不要编造数据，所有信息必须来自工具返回结果
- 不要给出具体的买卖操作指令（如"立即买入""建议卖出"）
- 不要忽略 warnings 和熔断信息
- 不要忽略风控预警：如有 risk_warning 或 alert_level 为 high/medium，必须在回复开头展示风控警告
- **不要暴露工具返回的原始错误信息**（如异常堆栈、错误码、`status=error` 等内部技术细节），用用户友好的措辞替代
- 不要自创输出规范中未定义的章节名（如"推荐结果概览""综合分析"等）

# 异常处理指南

遇到工具异常时，用以下**用户友好措辞**处理，**不要输出原始错误信息**：

| 场景 | ✅ 正确表述 | ❌ 错误表述 |
|------|-----------|-----------|
| 画像不存在 | 该客户暂未完成风险测评，建议引导客户完成测评问卷 | — |
| 画像查询失败 | 客户画像暂时无法获取，已基于历史数据完成匹配 | `画像查询失败` |
| 无风控预警 | **不展示风控章节** | "✅ 无风控预警 — 该客户当前无未处理的风控告警" |
| smart_recommend 返回 profile_not_found | 该客户风险测评已过期，系统已按最低风险等级(R1)匹配产品。建议引导客户重新测评。推荐结果如下： | — |
| 工具超时/异常 | 部分数据暂时无法获取，推荐结果供参考，建议稍后重试 | `Tool timeout` / `status=error` |

关键原则：**宁可说"不知道"，也不编造数据；宁可少说，也不暴露内部技术细节。**"""

class AdvisorAgent(BaseAgent):
    """
    投顾 Agent（LLM 驱动的多工具统一入口）

    与 ProfileAgent 同款模式：用 LangChain create_agent 将 LLM + 工具箱组合，
    LLM 根据 System Prompt 自行决定何时调用哪个工具。

    用法:
        agent = AdvisorAgent(db, session_id="xxx")
        result = await agent.execute("给客户张三推荐3款产品", customer_id=1)
        print(result["reply"])
    """

    def __init__(self, db: AsyncSession, session_id: str = ""):
        super().__init__(db, session_id)
        self._settings = get_settings()

        # ── 初始化 LLM（投顾 Agent 单独压低 timeout，避免多轮工具调用叠加超时）──
        self._llm = ChatOpenAI(
            model=self._settings.llm.openai_model_chat,
            temperature=self._settings.llm.openai_temperature,
            max_tokens=self._settings.llm.openai_max_tokens,
            timeout=60,
            max_retries=1,
            openai_api_key=self._settings.llm.openai_api_key,
            base_url=self._settings.llm.openai_base_url,
        )

        # ── 初始化内置工具（需要 db session 的动态工具） ──
        self._profile_tool = ProfileTool(db=db)
        self._holding_tool = HoldingTool(db=db)
        self._comparison_tool = ComparisonTool(db=db)

        # recommend_products 和 asset_allocation 需要 db session，
        # 在 __init__ 中用闭包创建 @tool 函数
        self._recommend_tool = self._make_recommend_tool(db)
        self._allocation_tool = self._make_allocation_tool(db)
        self._holding_func_tool = self._make_holding_tool(db)
        self._smart_recommend_tool = self._make_smart_recommend_tool(db)

        # ── 创建 LangChain Agent ──
        self._agent = create_agent(
            model=self._llm,
            tools=[
                self._smart_recommend_tool,  # 一键推荐放在最前面，LLM 优先看到
                self._profile_tool,
                self._comparison_tool,
                self._holding_func_tool,
                self._recommend_tool,
                self._allocation_tool,
                graphrag_tool,       # 无状态，直接用模块级 @tool
            ],
            system_prompt=ADVISOR_SYSTEM_PROMPT,
        )

    # ═══════════════════════════════════════════════════════════════
    # 对外接口
    # ═══════════════════════════════════════════════════════════════

    async def execute(self, message: str, **kwargs) -> dict:
        """
        Agent 主入口

        Args:
            message: 用户自然语言输入
            **kwargs: customer_id（可选）

        Returns:
            {"reply": str, "recommendations": list, "customer_profile": dict,
             "holdings_analysis": dict, "reasoning": str, "session_id": str}
        """
        customer_id = kwargs.get("customer_id")

        # ── 意图分类（轻量预筛，辅助LLM更快决策）──
        advisor_intent = None
        advisor_intent_confidence = 0.0
        try:
            from app.service.intent_service import get_intent_service
            intent_svc = get_intent_service()
            advisor_intent, advisor_intent_confidence = await intent_svc.classify_advisor(message)
            logger.info(
                f"投顾意图分类: {advisor_intent} (置信度: {advisor_intent_confidence:.2f})"
            )
        except Exception as e:
            logger.warning(f"投顾意图分类失败(不影响主流程): {e}")

        # ── 跨 session 记忆召回（长期记忆：画像摘要 + 历史偏好）──
        cross_session_context = ""
        if customer_id:
            try:
                from app.service.memory_recall_service import get_memory_recall_service
                memory_recall = get_memory_recall_service()
                user_profile = await memory_recall.build_user_profile_summary(self.db, customer_id)
                historical_prefs = await memory_recall.recall_historical_preferences(self.db, customer_id)
                if user_profile:
                    cross_session_context += f"\n\n[客户画像]\n{user_profile}"
                if historical_prefs:
                    cross_session_context += f"\n\n[历史偏好]\n{historical_prefs}"
                if cross_session_context:
                    logger.info(f"投顾Agent跨session记忆召回完成 | customer_id={customer_id}")
            except Exception as e:
                logger.warning(f"投顾Agent跨session记忆召回失败(不影响主流程): {e}")
                try:
                    from app.api.admin import inc_metric
                    inc_metric("memory_recall_failures")
                except Exception:
                    pass

        # ── 记忆召回：短期记忆（同 session 多轮，基于 token 限制而非固定条数）──
        history_messages: list[HumanMessage] = []
        if self.memory:
            try:
                from langchain_core.messages import AIMessage

                history = await self.memory.get_messages(max_tokens=4096)  # 增加到 4096 tokens
                # 从最新到最旧取消息，直到接近 token 限制（简单估算：1 char ≈ 0.5 token）
                estimated_tokens = 0
                max_history_tokens = 3000  # 留给历史的 token 预算
                selected = []
                for msg in reversed(history):
                    content = msg.get("content", "")
                    if not content:
                        continue
                    char_count = len(content)
                    est = char_count // 2  # 粗略估算
                    if estimated_tokens + est > max_history_tokens:
                        break
                    estimated_tokens += est
                    selected.append(msg)
                selected.reverse()  # 恢复时间顺序

                for msg in selected:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role == "user":
                        history_messages.append(HumanMessage(content=content))
                    else:
                        history_messages.append(AIMessage(content=content))
            except Exception as e:
                logger.warning(f"投顾Agent记忆召回失败: {e}")

        # 构造当前用户消息（注入 customer_id 上下文 + 意图提示 + 跨session记忆）
        user_message = self._build_user_message(message, customer_id)
        if advisor_intent and advisor_intent_confidence >= 0.80:
            intent_hint = self._build_intent_hint(advisor_intent)
            user_message = user_message + "\n\n" + intent_hint
        if cross_session_context:
            user_message = user_message + cross_session_context

        # 组装完整消息列表：历史 + 当前
        all_messages = history_messages + [HumanMessage(content=user_message)]

        try:
            import asyncio
            result = await asyncio.wait_for(
                self._agent.ainvoke(
                    {"messages": all_messages},
                    config={"recursion_limit": 6},
                ),
                timeout=180,
            )
        except asyncio.TimeoutError:
            logger.warning("AdvisorAgent 执行超时(180s)，返回降级提示")
            try:
                from app.api.admin import inc_metric
                inc_metric("agent_timeouts")
            except Exception:
                pass
            return {
                "reply": "投顾分析超时，请尝试简化问题或稍后重试。",
                "recommendations": [],
                "customer_profile": None,
                "holdings_analysis": None,
                "reasoning": None,
                "session_id": self.session_id,
            }
        except Exception as e:
            logger.error(f"AdvisorAgent 执行失败: {e}", exc_info=True)
            try:
                from app.api.admin import inc_metric
                inc_metric("agent_errors")
            except Exception:
                pass
            return {
                "reply": f"投顾服务暂时不可用，请稍后重试。错误详情：{str(e)}",
                "recommendations": [],
                "customer_profile": None,
                "holdings_analysis": None,
                "reasoning": None,
                "session_id": self.session_id,
            }

        reply = self._extract_reply(result)
        # 优先从 smart_recommend 提取（新的一键推荐工具），
        # 其次回退到单独工具提取（兼容旧路径）
        smart_rec = self._extract_tool_result(result, "smart_recommend")
        if smart_rec:
            recommendations = smart_rec.get("recommendations", [])
            customer_profile = smart_rec.get("customer_profile")
            allocation = smart_rec.get("allocation")
        else:
            recommendations = self._extract_tool_result(result, "recommend_products")
            customer_profile = self._extract_tool_result(result, "profile_tool")
            allocation = None
        holdings_analysis = self._extract_tool_result(result, "analysis_holdings")
        reasoning = self._extract_reasoning(result)

        # ── 记忆写入：保存本轮对话到短期记忆 + 异步归档 ──
        if self.memory:
            try:
                await self.memory.add_message("user", message)
                await self.memory.add_message("assistant", reply)
            except Exception as e:
                logger.warning(f"投顾Agent记忆写入失败: {e}")

        return {
            "reply": reply,
            "recommendations": recommendations,
            "customer_profile": customer_profile,
            "allocation": allocation,
            "holdings_analysis": holdings_analysis,
            "reasoning": reasoning,
            "session_id": self.session_id,
        }

    async def stream_execute(self, message: str, **kwargs):
        """
        流式执行 Agent，逐 token yield 事件字典。

        事件类型:
          {"type": "meta", "agent": "advisor", "session_id": "..."}
          {"type": "token", "content": "为"}        # LLM 逐 token
          {"type": "tool_end", "name": "smart_recommend"}
          {"type": "done", "reply": "...", "recommendations": [...], ...}
          {"type": "error", "message": "..."}
        """
        import json as _json
        import asyncio

        customer_id = kwargs.get("customer_id")

        # ── 预处理：意图分类 + 记忆召回 + 消息构造（同 execute）──
        cross_session_context = ""
        if customer_id:
            try:
                from app.service.memory_recall_service import get_memory_recall_service
                memory_recall = get_memory_recall_service()
                user_profile = await memory_recall.build_user_profile_summary(self.db, customer_id)
                historical_prefs = await memory_recall.recall_historical_preferences(self.db, customer_id)
                if user_profile:
                    cross_session_context += f"\n\n[客户画像]\n{user_profile}"
                if historical_prefs:
                    cross_session_context += f"\n\n[历史偏好]\n{historical_prefs}"
            except Exception:
                pass

        history_messages: list[HumanMessage] = []
        if self.memory:
            try:
                from langchain_core.messages import AIMessage
                history = await self.memory.get_messages(max_tokens=4096)
                estimated_tokens = 0
                selected = []
                for msg in reversed(history):
                    content = msg.get("content", "")
                    if not content:
                        continue
                    if estimated_tokens + len(content) // 2 > 3000:
                        break
                    estimated_tokens += len(content) // 2
                    selected.append(msg)
                selected.reverse()
                for msg in selected:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role == "user":
                        history_messages.append(HumanMessage(content=content))
                    else:
                        history_messages.append(AIMessage(content=content))
            except Exception:
                pass

        user_message = self._build_user_message(message, customer_id)
        if cross_session_context:
            user_message = user_message + cross_session_context
        all_messages = history_messages + [HumanMessage(content=user_message)]

        yield {"type": "meta", "agent": "advisor", "session_id": self.session_id}

        # ── 流式执行 LangChain Agent ──
        full_reply = ""
        tool_outputs: dict[str, dict] = {}

        try:
            async def _stream_agent():
                async for event in self._agent.astream_events(
                    {"messages": all_messages},
                    config={"recursion_limit": 6},
                    version="v2",
                ):
                    yield event

            stream = _stream_agent()
            while True:
                try:
                    event = await asyncio.wait_for(stream.__anext__(), timeout=180)
                except asyncio.TimeoutError:
                    yield {"type": "error", "message": "投顾分析超时，请尝试简化问题或稍后重试。"}
                    break

                kind = event.get("event", "")

                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk:
                        token = getattr(chunk, "content", None)
                        if token and isinstance(token, str):
                            full_reply += token
                            yield {"type": "token", "content": token}

                elif kind == "on_tool_end":
                    name = event.get("name", "")
                    output = event.get("data", {}).get("output", {})
                    # 工具输出可能是 ToolMessage / JSON 字符串 / dict，统一提取
                    if hasattr(output, "content"):
                        # LangChain ToolMessage / AIMessage 等消息对象
                        raw_content = getattr(output, "content", "")
                        if isinstance(raw_content, str):
                            try:
                                output = _json.loads(raw_content)
                            except (_json.JSONDecodeError, TypeError):
                                output = {"raw": raw_content}
                        else:
                            output = {"raw": str(raw_content)}
                    elif isinstance(output, str):
                        try:
                            output = _json.loads(output)
                        except (_json.JSONDecodeError, TypeError):
                            output = {"raw": output}
                    tool_outputs[name] = output
                    yield {"type": "tool_end", "name": name}

                elif kind == "on_chain_end" and event.get("name") == "LangGraph":
                    break

        except StopAsyncIteration:
            pass
        except Exception as e:
            logger.error(f"AdvisorAgent 流式执行失败: {e}", exc_info=True)
            yield {"type": "error", "message": f"投顾服务暂时不可用：{str(e)}"}
            return

        # ── 从工具输出提取结构化数据（同 execute 逻辑）──
        smart_rec = tool_outputs.get("smart_recommend")
        recommendations = smart_rec.get("recommendations", []) if smart_rec else []
        customer_profile = smart_rec.get("customer_profile") if smart_rec else None
        allocation = smart_rec.get("allocation") if smart_rec else None
        if not smart_rec:
            rec_result = tool_outputs.get("recommend_products")
            recommendations = rec_result if rec_result else []
            profile_result = tool_outputs.get("profile_tool")
            customer_profile = profile_result if profile_result else None

        holdings_analysis = tool_outputs.get("analysis_holdings")

        # ── 记忆写入 ──
        if self.memory and full_reply:
            try:
                await self.memory.add_message("user", message)
                await self.memory.add_message("assistant", full_reply)
            except Exception:
                pass

        # The streaming path must meet the same suitability disclosure
        # requirement as the regular advisor API.  A deterministic narrative
        # also keeps the UI useful if the model returns no natural-language
        # summary after invoking a recommendation tool.
        from app.service.advisor_narrative_service import AdvisorNarrativeService
        narrative_service = AdvisorNarrativeService()
        final_reply = (
            narrative_service.ensure_disclaimer(full_reply)
            if full_reply
            else narrative_service.render_template({
                "customer_profile": customer_profile,
                "recommendations": recommendations,
            })
        )

        yield {
            "type": "done",
            "reply": final_reply,
            "narrative": final_reply,
            "recommendations": recommendations,
            "customer_profile": customer_profile,
            "allocation": allocation,
            "holdings_analysis": holdings_analysis,
            "session_id": self.session_id,
        }

    async def run(self, message: str, customer_id: Optional[int] = None) -> dict:
        """便捷方法"""
        return await self.execute(message, customer_id=customer_id)

    # ═══════════════════════════════════════════════════════════════
    # 工具工厂方法
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _make_smart_recommend_tool(db: AsyncSession):
        """创建一键智能推荐工具（画像+风险预警检查+推荐+配置，一次工具调用完成）"""
        from app.tool.profile_tool import ProfileTool
        from app.tool.recommendation_tool import RecommendationTool
        from app.tool.allocation_tool import AllocationTool

        profile_tool = ProfileTool(db=db)
        rec_tool = RecommendationTool(db)
        alloc_tool = AllocationTool(db)

        @tool
        async def smart_recommend(customer_id: int, top_n: int = 3) -> str:
            """
            一键智能推荐工具：自动完成客户画像查询 + 风控预警检查 + 产品推荐 + 资产配置建议。

            当用户要求"推荐产品""适合什么产品""买什么好""有什么推荐"时，
            优先调用此工具，不需要先调 profile_tool 再调 recommend_products。

            此工具内部会：
            1. 检查客户是否有未处理的风控预警（高风险客户限制推荐R1-R2产品）
            2. 顺序读取客户画像和资产配置，避免共享数据库会话并发访问
            3. 综合风险预警和画像等级给出推荐

            重要：如果客户画像不存在（status=not_found），会回退推荐R1最低风险产品，
            并提示用户完成风评问卷。不要因此返回空结果或拒绝推荐。

            Args:
                customer_id: 客户ID
                top_n: 返回 Top N 个推荐产品，默认 3

            Returns:
                JSON 格式的一站式结果，包含客户画像摘要、风控预警状态、产品推荐列表、资产配置建议
            """
            import json
            from datetime import datetime as dt, timedelta
            from sqlalchemy import text, select, func
            from app.model.entities import FinRiskAlert

            # ── Issue #6 修复：检查风控预警状态 ──
            risk_alerts = []
            risk_alert_level = "none"
            try:
                thirty_days_ago = dt.now() - timedelta(days=30)
                alert_result = await db.execute(
                    select(FinRiskAlert)
                    .where(
                        FinRiskAlert.customer_id == customer_id,
                        FinRiskAlert.status == "pending",
                    )
                    .order_by(FinRiskAlert.create_time.desc())
                    .limit(10)
                )
                alerts = alert_result.scalars().all()
                risk_alerts = [
                    {
                        "alert_id": a.id,
                        "alert_type": a.alert_type,
                        "alert_level": a.alert_level,
                        "trigger_detail": (a.trigger_detail or "")[:200],
                        "created_at": str(a.create_time) if a.create_time else None,
                    }
                    for a in alerts
                ]
                # 确定最高风险预警级别
                high_count = sum(1 for a in risk_alerts if a["alert_level"] == "high")
                medium_count = sum(1 for a in risk_alerts if a["alert_level"] == "medium")
                if high_count > 0:
                    risk_alert_level = "high"
                elif medium_count > 0:
                    risk_alert_level = "medium"
                elif risk_alerts:
                    risk_alert_level = "low"
            except Exception as e:
                logger.warning(f"风控预警查询失败 customer={customer_id}: {e}")

            # AsyncSession is not safe for concurrent queries. Resolve the
            # profile first so a real C3 profile can never be replaced by a
            # transient allocation-query error.
            try:
                profile_json = await profile_tool._arun(customer_id)
            except Exception as exc:
                logger.warning("smart_recommend profile query failed: %s", exc)
                profile_json = json.dumps({"customer_id": customer_id, "status": "error"})

            try:
                alloc_result = await alloc_tool.get_allocation(customer_id)
            except Exception as exc:
                logger.warning("smart_recommend allocation query failed: %s", exc)
                alloc_result = {}

            # 解析画像获取风险等级，传给推荐
            try:
                profile_data = json.loads(profile_json)
            except (json.JSONDecodeError, TypeError):
                profile_data = {"risk_level": "C2", "status": "parse_error"}

            risk_level = None
            profile_not_found = False
            if isinstance(profile_data, dict):
                if profile_data.get("status") == "not_found":
                    profile_not_found = True
                    # ── 自动修复：画像缺失时主动执行研判创建画像 ──
                    try:
                        from app.service.profile_service import ProfileService
                        profile_svc = ProfileService(db)
                        assess_result = await profile_svc.assess(customer_id, trigger_type="auto_recovery")
                        risk_level = assess_result.risk_level
                        profile_not_found = False  # 画像已创建
                        profile_data = {
                            "customer_id": customer_id,
                            "assessment": {
                                "risk_level": assess_result.risk_level,
                                "risk_level_name": _level_to_name_static(assess_result.risk_level),
                                "total_score": assess_result.total_score,
                                "confidence_score": assess_result.confidence_score,
                            },
                            "basic_info": {"name": "客户" + str(customer_id)},
                            "status": "recovered",
                        }
                        logger.info(f"smart_recommend 自动修复画像成功 | customer_id={customer_id} | risk_level={risk_level}")
                    except Exception as recovery_err:
                        logger.warning(
                            f"smart_recommend 自动修复画像失败(回退C1) | customer_id={customer_id} | {recovery_err}"
                        )
                        risk_level = "C1"
                elif profile_data.get("status") in ("error", "parse_error"):
                    # 画像查询出错 → 尝试通过 assess() 修复
                    try:
                        from app.service.profile_service import ProfileService
                        profile_svc = ProfileService(db)
                        assess_result = await profile_svc.assess(customer_id, trigger_type="auto_recovery")
                        risk_level = assess_result.risk_level
                        profile_data = {
                            "customer_id": customer_id,
                            "assessment": {
                                "risk_level": assess_result.risk_level,
                                "risk_level_name": _level_to_name_static(assess_result.risk_level),
                                "total_score": assess_result.total_score,
                                "confidence_score": assess_result.confidence_score,
                            },
                            "basic_info": {"name": "客户" + str(customer_id)},
                            "status": "recovered",
                        }
                        logger.info(f"smart_recommend 修复异常画像成功 | customer_id={customer_id}")
                    except Exception:
                        risk_level = "C2"
                else:
                    assessment = profile_data.get("assessment", {})
                    risk_level = assessment.get("risk_level")

            # ── Issue #6 修复：高风险客户限制产品推荐范围 ──
            effective_top_n = top_n
            restricted_risk = None
            if risk_alert_level == "high":
                # 高风险预警客户：限制只能推荐 R1-R2 产品
                restricted_risk = "C2"  # 对应 R2
                effective_top_n = max(top_n, 5)  # 多取一些以防过滤后不够
                logger.info(
                    "客户 %s 存在高风险预警，产品推荐限制为 R1-R2",
                    customer_id,
                )
            elif risk_alert_level == "medium":
                # 中风险预警客户：限制只能推荐 R1-R3 产品
                restricted_risk = "C3"  # 对应 R3
                logger.info(
                    "客户 %s 存在中风险预警，产品推荐限制为 R1-R3",
                    customer_id,
                )

            # 用风控限制后的风险等级做推荐
            effective_risk = restricted_risk or risk_level
            rec_result = await rec_tool.recommend(customer_id, effective_top_n, fallback_risk=effective_risk)

            # ── Issue #6 修复：对高风险客户过滤推荐结果 ──
            recommendations = rec_result.get("recommendations", [])
            if risk_alert_level in ("high", "medium"):
                max_allowed_risk = 2 if risk_alert_level == "high" else 3  # R2 or R3
                recommendations = [
                    r for r in recommendations
                    if AdvisorAgent._product_risk_num(r.get("risk_level", "R5")) <= max_allowed_risk
                ]
                # 如果过滤后不够 top_n，补足
                if len(recommendations) < top_n:
                    recommendations = recommendations[:top_n] if recommendations else []

            # 构建最终的推荐结果
            rec_result_filtered = {
                **rec_result,
                "recommendations": recommendations[:top_n],
            }

            # 无画像时的处理（仅自动修复也失败时才会进入此分支）
            if profile_not_found:
                result = {
                    "customer_profile": profile_data,
                    "recommendations": rec_result_filtered.get("recommendations", []),
                    "allocation": alloc_result,
                    "reasoning": rec_result_filtered.get("reasoning", ""),
                    "risk_alerts": {
                        "alert_level": risk_alert_level,
                        "alert_count": len(risk_alerts),
                        "alerts": risk_alerts,
                    },
                    "status": "profile_not_found",
                    "notice": (
                        "⚠️ 该客户暂未完成风险测评，系统已按最低风险等级（C1保守型）匹配产品。"
                        "建议引导客户完成风险测评以获得更精准的推荐。"
                        "风评问卷入口：点击「开始风评测评」按钮或访问 /api/risk/questionnaire"
                    ),
                }
            else:
                result = {
                    "customer_profile": profile_data,
                    "recommendations": rec_result_filtered.get("recommendations", []),
                    "allocation": alloc_result,
                    "reasoning": rec_result_filtered.get("reasoning", ""),
                    "risk_alerts": {
                        "alert_level": risk_alert_level,
                        "alert_count": len(risk_alerts),
                        "alerts": risk_alerts,
                    },
                }
                # 高风险客户添加风控警告
                if risk_alert_level == "high":
                    result["risk_warning"] = (
                        "🚨 该客户存在高风险预警（未处理），系统已自动将产品推荐限制为 R1-R2 低风险产品。"
                        "建议联系风控专员处理预警后再推荐高风险产品。"
                    )
                elif risk_alert_level == "medium":
                    result["risk_warning"] = (
                        "⚠️ 该客户存在中风险预警，系统已将产品推荐限制为 R1-R3 中低风险产品。"
                    )

            return json.dumps(result, ensure_ascii=False, default=_json_default)

        return smart_recommend

    @staticmethod
    def _product_risk_num(risk_level: str) -> int:
        """将风险等级字符串转为数字，用于比较过滤"""
        if not risk_level:
            return 5
        level = str(risk_level).strip().upper()
        if level in ("R1", "C1"):
            return 1
        if level in ("R2", "C2"):
            return 2
        if level in ("R3", "C3"):
            return 3
        if level in ("R4", "C4"):
            return 4
        return 5

    @staticmethod
    def _make_recommend_tool(db: AsyncSession):
        """创建产品推荐工具（闭包捕获 db session）"""
        from app.tool.recommendation_tool import RecommendationTool
        rec_tool = RecommendationTool(db)

        @tool
        async def recommend_products(customer_id: int, top_n: int = 3) -> str:
            """
            根据客户风险画像推荐匹配的金融产品。

            Args:
                customer_id: 客户ID
                top_n: 返回 Top N 个推荐产品，默认 3

            Returns:
                JSON 格式的推荐结果，包含产品代码、名称、风险等级、预期收益、匹配评分和推荐理由
            """
            result = await rec_tool.recommend(customer_id, top_n)
            import json
            return json.dumps(result, ensure_ascii=False, default=_json_default)

        return recommend_products

    @staticmethod
    def _make_allocation_tool(db: AsyncSession):
        """创建资产配置工具（闭包捕获 db session）"""
        from app.tool.allocation_tool import AllocationTool
        alloc_tool = AllocationTool(db)

        @tool
        async def asset_allocation(customer_id: int) -> str:
            """
            为客户提供资产配置比例建议。

            Args:
                customer_id: 客户ID

            Returns:
                JSON 格式的配置结果，包含各资产类型配比、风险等级和配置说明
            """
            result = await alloc_tool.get_allocation(customer_id)
            import json
            return json.dumps(result, ensure_ascii=False, default=_json_default)

        return asset_allocation

    @staticmethod
    def _make_holding_tool(db: AsyncSession):
        """创建持仓分析工具（闭包捕获 db session，内部调用 Neo4j + MySQL）"""
        holding_tool = HoldingTool(db)

        @tool
        async def analysis_holdings(customer_id: int) -> str:
            """
            分析客户持仓分布、行业集中度和盈亏状态。

            该工具综合 MySQL 持仓明细和 Neo4j 行业关系图谱，返回：
            - 持仓明细（产品ID、市值、盈亏、盈亏比例）
            - 集中度分析（单产品占比、是否过度集中）
            - 行业分布（各行业持仓产品数量和名称）
            - 盈亏汇总（总市值、总盈亏、盈利/亏损产品数量）

            Args:
                customer_id: 客户ID

            Returns:
                JSON 格式的持仓综合分析结果
            """
            result = await holding_tool.analyze(customer_id)
            import json
            return json.dumps(result, ensure_ascii=False, default=_json_default)

        return analysis_holdings

    # ═══════════════════════════════════════════════════════════════
    # 内部辅助
    # ═══════════════════════════════════════════════════════════════

    def _build_user_message(self, message: str, customer_id: Optional[int]) -> str:
        """构造发送给 LLM 的用户消息，注入 customer_id 上下文"""
        if customer_id is not None:
            return (
                f"用户问题：{message}\n\n"
                f"（系统提示：当前客户ID为 {customer_id}，"
                f"如果用户提到该客户，调用工具时请使用 customer_id={customer_id}）"
            )
        return f"用户问题：{message}"

    @staticmethod
    def _build_intent_hint(intent: str) -> str:
        """根据投顾意图分类结果，生成轻量级工具提示（辅助LLM更快决策）"""
        hints = {
            "product_recommend": (
                "（意图提示：用户意图为「产品推荐」，优先调用 smart_recommend 工具）"
            ),
            "portfolio_analysis": (
                "（意图提示：用户意图为「持仓分析」，优先调用 analysis_holdings 工具）"
            ),
            "asset_allocation": (
                "（意图提示：用户意图为「资产配置」，优先调用 asset_allocation 工具）"
            ),
            "comparison": (
                "（意图提示：用户意图为「客户对比」，优先调用 compare_customers 工具）"
            ),
        }
        return hints.get(intent, "")

    @staticmethod
    def _extract_reply(result: dict) -> str:
        """从 Agent 结果中提取最后一条 AI 消息"""
        messages = result.get("messages", [])
        for msg in reversed(messages):
            content = getattr(msg, "content", None)
            if content and isinstance(content, str) and len(content) > 20:
                return content
            msg_type = getattr(msg, "type", "")
            if msg_type == "ai" and content:
                return content

        for msg in reversed(messages):
            content = getattr(msg, "content", None)
            if content:
                return str(content)

        return "未能获取分析结果，请重试。"

    @staticmethod
    def _extract_tool_result(result: dict, tool_name: str):
        """从 Agent 消息中提取指定工具的返回结果（解析 JSON）"""
        import json
        messages = result.get("messages", [])
        for msg in messages:
            # LangChain ToolMessage: name 属性标识工具名
            msg_name = getattr(msg, "name", "")
            if msg_name != tool_name:
                continue
            content = getattr(msg, "content", None)
            if not content or not isinstance(content, str):
                continue
            try:
                return json.loads(content)
            except (json.JSONDecodeError, TypeError):
                # 非 JSON 文本，直接返回字符串
                return {"raw": content}
        return None

    @staticmethod
    def _extract_reasoning(result: dict) -> str:
        """从 Agent 消息中提取推理/思考内容"""
        messages = result.get("messages", [])
        for msg in reversed(messages):
            content = getattr(msg, "content", None)
            # 取最后一条 AI 消息的前 200 字作为推理摘要
            if content and isinstance(content, str) and len(content) > 50:
                return content[:200] + ("..." if len(content) > 200 else "")
        return None
