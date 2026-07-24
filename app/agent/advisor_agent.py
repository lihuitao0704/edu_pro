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

回答时请使用 Markdown 格式，包含以下结构（按需裁剪，不必全部都有）：

```
## 📊 客户风险画像
（如果调了 profile_tool 或 smart_recommend，展示基本信息 + 四维度得分 + 风险等级 + 熔断告警）

## 🎯 产品推荐
（如果调了 smart_recommend 或 recommend_products，列出推荐产品，含风险等级、预期收益、匹配度、推荐理由）

## 📐 资产配置建议
（如果调了 smart_recommend 或 asset_allocation，展示各资产类型配比和说明）

## 🔄 客户对比分析
（如果调了 compare_customers，展示两客户画像差异 + 共同持仓 + 行业重叠度 + 对比摘要）

## 💼 持仓分析
（如果调了 analysis_holdings，展示持仓明细 + 行业分布 + 集中度 + 盈亏状态）

## 🔍 知识检索结果
（如果调了 graphrag_search，展示检索到的行业/产品/文档信息）
```

# 语言风格
- 专业但不晦涩，面向理财顾问而非终端客户
- 数据驱动：每个结论都要引用具体数据
- 风险意识：如有熔断告警或 warnings，务必在回复中突出提醒
- 温度适中：不要过度热情，也不要冷冰冰

# 禁止事项
- 不要编造数据，所有信息必须来自工具返回结果
- 不要给出具体的买卖操作指令（如"立即买入"）
- 不要忽略 warnings 和熔断信息
- 如果工具返回了错误，诚实告知用户并说明原因

# 异常处理指南

当工具返回特定状态时，你必须按以下方式处理，不得自行编造数据：

| 工具 | 返回状态 | 处理方式 |
|------|---------|----------|
| `profile_tool` | `status=not_found` | 直接回复理财顾问："该客户暂无风险画像，建议先引导客户完成风险测评问卷。" 不要尝试编造画像数据。 |
| `smart_recommend` | `status=profile_not_found` | **重要！** 此时推荐列表中已包含R1级（最低风险）产品作为兜底推荐。你的回复必须：1) 先告知"当前您的风险评估已失效或不存在，建议您及时评测，维持有效的风评状态更方便购买财富产品"；2) 紧接着展示R1兜底推荐产品；3) 在回复末尾附加风评问卷入口：【📋 开始风评测评】(让用户点击即可进入问卷)。 |
| `profile_tool` | `status=error` | 如实告知查询失败及具体错误原因，不要猜测或编造客户信息。 |
| 任何工具 | 返回空或异常 | 诚实说明该工具暂时不可用，建议稍后重试或联系技术支持。 |

关键原则：**宁可说"不知道"，也不编造数据。** 金融场景下的错误信息可能导致合规风险。"""


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

        # ── 记忆召回：短期记忆（同 session 多轮） ──
        history_messages: list[HumanMessage] = []
        if self.memory:
            try:
                history = await self.memory.get_messages(max_tokens=2048)
                for msg in history[-6:]:  # 最多注入 3 轮（6 条）
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if not content:
                        continue
                    if role == "user":
                        history_messages.append(HumanMessage(content=content))
                    else:
                        from langchain_core.messages import AIMessage

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
        else:
            recommendations = self._extract_tool_result(result, "recommend_products")
            customer_profile = self._extract_tool_result(result, "profile_tool")
        holdings_analysis = self._extract_tool_result(result, "analysis_holdings")
        reasoning = self._extract_reasoning(result)

        # ── 记忆写入：保存本轮对话到短期记忆 + 异步归档 ──
        if self.memory:
            try:
                await self.memory.add_message("user", message)
                await self.memory.add_message("assistant", reply)
            except Exception as e:
                logger.warning(f"投顾Agent记忆写入失败: {e}")

            # 异步归档到长期记忆（后台任务，不阻塞主流程）
            try:
                from app.service.memory_service import MemoryService
                memory_svc = MemoryService(self.db)
                await memory_svc.archive_turn(
                    session_id=self.session_id,
                    user_id=customer_id or 0,
                    agent_type="advisor",
                    user_content=message,
                    assistant_content=reply,
                )
                logger.info(f"投顾Agent归档已触发 | session={self.session_id}")
            except Exception as e:
                logger.warning(f"投顾Agent归档触发失败: {e}")

        return {
            "reply": reply,
            "recommendations": recommendations,
            "customer_profile": customer_profile,
            "holdings_analysis": holdings_analysis,
            "reasoning": reasoning,
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
        """创建一键智能推荐工具（画像+推荐+配置，一次工具调用完成）"""
        from app.tool.profile_tool import ProfileTool
        from app.tool.recommendation_tool import RecommendationTool
        from app.tool.allocation_tool import AllocationTool

        profile_tool = ProfileTool(db=db)
        rec_tool = RecommendationTool(db)
        alloc_tool = AllocationTool(db)

        @tool
        async def smart_recommend(customer_id: int, top_n: int = 3) -> str:
            """
            一键智能推荐工具：自动完成客户画像查询 + 产品推荐 + 资产配置建议。

            当用户要求"推荐产品""适合什么产品""买什么好""有什么推荐"时，
            优先调用此工具，不需要先调 profile_tool 再调 recommend_products。

            此工具内部并行查询画像和推荐，比分开调用快一倍。

            重要：如果客户画像不存在（status=not_found），会回退推荐R1最低风险产品，
            并提示用户完成风评问卷。不要因此返回空结果或拒绝推荐。

            Args:
                customer_id: 客户ID
                top_n: 返回 Top N 个推荐产品，默认 3

            Returns:
                JSON 格式的一站式结果，包含客户画像摘要、产品推荐列表、资产配置建议
            """
            import json
            import asyncio

            # 并行执行画像查询和产品推荐（互不依赖的数据并行获取）
            profile_coro = profile_tool._arun(customer_id)
            alloc_coro = alloc_tool.get_allocation(customer_id)

            # 先等画像结果回来（推荐需要知道风险等级）
            profile_json, alloc_result = await asyncio.gather(profile_coro, alloc_coro)

            # 解析画像获取风险等级，传给推荐
            try:
                profile_data = json.loads(profile_json)
            except (json.JSONDecodeError, TypeError):
                profile_data = {"risk_level": "C2", "status": "parse_error"}

            risk_level = None
            profile_not_found = False
            if isinstance(profile_data, dict):
                # 检查画像是否不存在
                if profile_data.get("status") == "not_found":
                    profile_not_found = True
                    risk_level = "C1"  # 无画像时回退到最低风险等级
                else:
                    assessment = profile_data.get("assessment", {})
                    risk_level = assessment.get("risk_level")

            # 用画像的风险等级做推荐
            rec_result = await rec_tool.recommend(customer_id, top_n, fallback_risk=risk_level)

            # 无画像时，确保返回最低风险产品和明确提示
            if profile_not_found:
                result = {
                    "customer_profile": profile_data,
                    "recommendations": rec_result.get("recommendations", []),
                    "allocation": alloc_result,
                    "reasoning": rec_result.get("reasoning", ""),
                    "status": "profile_not_found",
                    "notice": (
                        "⚠️ 该客户当前风险测评已失效或不存在，系统已回退推荐R1级（最低风险）产品。"
                        "建议客户及时完成【风评问卷】，维持有效的风评状态以便购买更多财富产品。"
                        "风评问卷入口：点击「开始风评测评」按钮或访问 /api/risk/questionnaire"
                    ),
                }
            else:
                result = {
                    "customer_profile": profile_data,
                    "recommendations": rec_result.get("recommendations", []),
                    "allocation": alloc_result,
                    "reasoning": rec_result.get("reasoning", ""),
                }

            return json.dumps(result, ensure_ascii=False, default=str)

        return smart_recommend

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
            return json.dumps(result, ensure_ascii=False, default=str)

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
            return json.dumps(result, ensure_ascii=False, default=str)

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
            return json.dumps(result, ensure_ascii=False, default=str)

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
