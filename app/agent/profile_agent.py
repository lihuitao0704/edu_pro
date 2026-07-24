"""
画像 Agent — LLM 驱动的风险画像分析与可解释性解读

使用 LangChain create_agent 框架：
  用户自然语言 → LLM 分析意图 → 调用 ProfileTool → LLM 生成通俗解读

严格遵循"第十五章 可解释性设计"：
  不仅输出等级，还要生成通俗易懂的风险解读，
  包含客户基本情况、各维度含义、综合等级、投资建议。
"""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from app.agent.base_agent import BaseAgent
from app.config.settings import get_settings
from app.tool.profile_tool import ProfileTool
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ══════════════════════════════════════════════════════════════════
# System Prompt — 风险画像分析师的"人设"
# ══════════════════════════════════════════════════════════════════

PROFILE_AGENT_SYSTEM_PROMPT = """# 角色
你是**专业的投资风险画像分析师**，就职于某大型券商的财富管理中心。
你能够调用工具查询客户风险画像，并用通俗易懂的语言向理财顾问解释分析结果。

# 核心职责
1. 当用户询问客户的风险等级、投资画像、风险评估时，**必须调用 `profile_tool`** 获取数据
2. 基于工具返回的 JSON 数据，生成一段**通俗、完整、有温度**的风险解读
3. 解读中必须明确告知风险等级和综合评分

# 可解释性解读规范（必须遵守）

## 输出结构
请按以下结构组织你的回复，使用 Markdown 格式：

```
## 🔍 客户风险画像解读

### 📋 客户概览
（一句话概括客户基本情况：年龄、职业、投资经验、资产规模）

### 📊 综合评定
- **风险等级**：C1-C5 + 中文名称
- **综合评分**：X / 100 分
- **置信度**：XX%

### 🔬 四维度深度分析
逐维度解读得分含义，每个维度必须说明：
  1. 该维度的满分是多少
  2. 客户实际得分
  3. 得分背后的原因（结合 detail 字段中的子项分数）
  4. 通俗说明这个分数意味着什么

### ⚠️ 风险提示
（如果触发了熔断规则或有 warnings，必须逐条列出并解释影响）

### 💡 投资建议
- 该客户适合的产品类型
- 需要特别注意的事项
```

## 解读语言风格
- **通俗易懂**：避免专业术语堆砌，用生活化语言解释
- **有温度**：像一位经验丰富的理财顾问在给客户做分析
- **数据支撑**：每个结论都要引用具体的评分数据
- **示例口吻**："鉴于您有5年投资经验且偏好固收类产品，基础属性得分18.5，风险偏好得分15.0，综合评定为稳健型(C2)……"

## 特殊情况处理
- 如果工具返回了 error 字段，礼貌告知用户查询失败并说明原因
- 如果触发了熔断规则（circuit_breakers），务必重点提示
- 如果某个维度得分偏低，给出改善建议
- 推荐产品时，解释为什么这些产品适合该客户

## 禁止事项
- 不要编造数据，所有分析必须基于工具返回的 JSON
- 不要省略 warnings 中的风险提示
- 不要给出具体的产品购买建议（代码），只说产品类型/等级
"""


class ProfileAgent(BaseAgent):
    """
    画像分析 Agent（LLM 驱动）

    使用 LangChain create_agent 框架，LLM 自动决定何时调用 ProfileTool。
    收到工具返回的画像 JSON 后，LLM 按 System Prompt 规范生成可解释性解读。

    用法:
        agent = ProfileAgent(db, session_id="xxx")
        result = await agent.run("评估客户张三的风险等级", customer_id=1)
        print(result["reply"])
    """

    def __init__(self, db: AsyncSession, session_id: str = ""):
        super().__init__(db, session_id)
        self._settings = get_settings()

        # ── 初始化 LLM ──
        self._llm = ChatOpenAI(
            model=self._settings.llm.openai_model_chat,
            temperature=self._settings.llm.openai_temperature,
            max_tokens=self._settings.llm.openai_max_tokens,
            timeout=self._settings.llm.openai_timeout,
            max_retries=self._settings.llm.openai_max_retries,
            openai_api_key=self._settings.llm.openai_api_key,
            base_url=self._settings.llm.openai_base_url,
        )

        # ── 初始化工具 ──
        self._profile_tool = ProfileTool(db=db)

        # ── 创建 LangChain Agent ──
        self._prompt = ChatPromptTemplate.from_messages([
            ("system", PROFILE_AGENT_SYSTEM_PROMPT),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ])
        self._agent = create_agent(
            model=self._llm,
            tools=[self._profile_tool],
            system_prompt=PROFILE_AGENT_SYSTEM_PROMPT,
        )

    async def _run_agent(self, input_text: str) -> dict:
        """统一执行 agent（兼容 create_agent 的 ainvoke 接口）"""
        result = await self._agent.ainvoke(
            {"messages": [HumanMessage(content=input_text)]},
            config={"recursion_limit": 4},
        )
        return result

    # ═══════════════════════════════════════════════════════════════
    # 对外接口
    # ═══════════════════════════════════════════════════════════════

    async def execute(self, message: str, **kwargs) -> dict:
        """
        Agent 主入口（兼容 BaseAgent 接口）

        Args:
            message: 用户自然语言输入，如 "评估客户张三的风险等级"
            **kwargs: customer_id（可选，如果用户消息中已包含客户ID则可省略）

        Returns:
            {"reply": "LLM 生成的可解释性解读", "session_id": "..."}
        """
        customer_id = kwargs.get("customer_id")

        # 构造发送给 LLM 的消息
        user_message = self._build_user_message(message, customer_id)
        try:
            result = await self._run_agent(user_message)
        except Exception as e:
            logger.error(f"Agent 执行失败: {e}")
            return {
                "reply": "画像分析服务暂时不可用，请稍后重试。",
                "session_id": self.session_id,
            }

        # 提取最后一条 AI 消息作为回复
        reply = self._extract_reply(result)
        return {
            "reply": reply,
            "session_id": self.session_id,
        }

    async def run(self, message: str, customer_id: Optional[int] = None) -> dict:
        """
        便捷方法：直接传入消息和客户ID，返回 Agent 回复。

        Args:
            message: 用户自然语言，如 "帮我看看客户1001的风险等级"
            customer_id: 客户ID（可选，如果消息中已包含）

        Returns:
            {"reply": str, "session_id": str}
        """
        return await self.execute(message, customer_id=customer_id)

    # ═══════════════════════════════════════════════════════════════
    # 内部辅助
    # ═══════════════════════════════════════════════════════════════

    def _build_user_message(self, message: str, customer_id: Optional[int]) -> str:
        """构造发送给 LLM 的用户消息，自动注入 customer_id 上下文"""
        if customer_id is not None:
            return (
                f"用户问题：{message}\n\n"
                f"（系统提示：客户ID为 {customer_id}，请直接调用 profile_tool 查询）"
            )
        return f"用户问题：{message}"

    @staticmethod
    def _extract_reply(result: dict) -> str:
        """从 Agent 结果中提取 AI 回复"""
        output = result.get("output", "")
        if output and isinstance(output, str):
            return output

        # 兜底：从 messages 中找最后一条 AI 消息
        messages = result.get("messages", [])
        for msg in reversed(messages):
            msg_type = getattr(msg, "type", "")
            content = getattr(msg, "content", None)
            if msg_type == "ai" and content:
                return content

        # 再兜底：返回最后一条有内容的消息
        for msg in reversed(messages):
            content = getattr(msg, "content", None)
            if content:
                return str(content)

        return "未能获取分析结果，请重试。"
