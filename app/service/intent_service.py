"""
Intent Service — 意图识别服务
基于 LLM 的意图分类：
  - 客服意图（5类）：product_inquiry / policy_interpretation / faq / chitchat / transfer_human
  - 投顾意图（4类）：product_recommend / portfolio_analysis / asset_allocation / comparison
"""

from typing import Optional, Tuple
from pathlib import Path

from app.tool.llm_tool import get_llm_tool
from app.utils.logger import get_logger

logger = get_logger("service.intent")

# ── 客服意图（原有） ──
INTENT_PRIORITY = {
    "transfer_human": 5,
    "faq": 4,
    "product_inquiry": 3,
    "policy_interpretation": 2,
    "chitchat": 1,
}

INTENT_TO_KNOWLEDGE_TYPE = {
    "product_inquiry": "product_knowledge",
    "policy_interpretation": "policy_knowledge",
    "faq": "faq_knowledge",
}

# ── 投顾意图（新增） ──
ADVISOR_INTENT_PRIORITY = {
    "portfolio_analysis": 4,
    "asset_allocation": 3,
    "product_recommend": 2,
    "comparison": 1,
}

ADVISOR_INTENT_TO_AGENT_ACTION = {
    "product_recommend": "recommend_products",
    "portfolio_analysis": "analysis_holdings",
    "asset_allocation": "asset_allocation",
    "comparison": "compare_customers",
}

ADVISOR_INTENT_DESCRIPTIONS = {
    "product_recommend": "产品推荐",
    "portfolio_analysis": "持仓分析",
    "asset_allocation": "资产配置",
    "comparison": "对比分析",
}


class IntentService:
    """意图识别服务"""

    def __init__(self):
        self.llm = get_llm_tool()
        self.prompt_template = self._load_prompt("intent_classify.txt", self._default_prompt)
        self.advisor_prompt_template = self._load_prompt(
            "advisor_intent_classify.txt", self._default_advisor_prompt
        )

    def _load_prompt(self, filename: str, fallback_fn) -> str:
        """加载 Prompt 模板文件，不存在则回退为内联默认模板"""
        prompt_dir = Path(__file__).parent.parent / "prompts"
        prompt_path = prompt_dir / filename
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        else:
            logger.warning(f"Prompt 文件不存在: {prompt_path}，使用默认模板")
            return fallback_fn()

    def _default_prompt(self) -> str:
        """默认客服意图识别 Prompt"""
        return """你是一个金融客服意图识别器。请根据用户输入判断其意图类别。

可选类别：
- product_inquiry：咨询理财产品（收益、类型、期限、风险等级、起投金额等）
- policy_interpretation：询问政策法规（资管新规、适当性管理、反洗钱等）
- faq：常见问题（申购确认时间、赎回规则、手续费等）
- chitchat：闲聊、问候、与金融业务无关的话题
- transfer_human：要求转接人工客服

示例：
用户："有什么年化5%以上的稳健型理财？" → product_inquiry
用户："基金申购后多久确认？" → faq
用户："资管新规对我的理财有什么影响？" → policy_interpretation
用户："你好" → chitchat
用户："我要找人工客服" → transfer_human

请仅输出意图类别标识符，不要输出其他内容。

用户输入："{user_message}"
意图："""

    def _default_advisor_prompt(self) -> str:
        """默认投顾意图识别 Prompt"""
        return """你是一个投顾意图分类专家。请分析用户输入，将其归类为以下四种投顾意图之一。

可选类别：
- product_recommend：用户要求推荐金融产品、筛选基金、找合适的产品
- portfolio_analysis：用户要求分析持仓、看持仓结构、行业分布、集中度、盈亏情况
- asset_allocation：用户要求资产配置建议、仓位比例调整、分配方案
- comparison：用户要求对比两个客户、比较画像差异、看有什么不同

示例：
用户："给我推荐几款R3级别的基金" → product_recommend
用户："帮我看看张三的持仓集中度怎么样" → portfolio_analysis
用户："我的资产应该怎么分配比较合理" → asset_allocation
用户："比较一下张三和李四的投资风格有什么不同" → comparison

请仅输出意图类别标识符，不要输出其他内容。

用户输入："{user_query}"
意图："""

    async def classify(self, message: str, history: Optional[list] = None) -> Tuple[str, float]:
        """
        意图分类

        Args:
            message: 用户消息
            history: 对话历史（可选，用于上下文理解）
        Returns:
            (intent, confidence) 意图类别和置信度
        """
        # 构建 Prompt
        prompt = self.prompt_template.format(user_message=message)

        try:
            # 调用 LLM 分类
            result = await self.llm.classify(prompt, temperature=0.1)
            result = result.strip()

            # 从推理文本中提取意图标签
            # 推理模型可能返回思考过程，需要提取最终答案
            intent = self._extract_intent_from_text(result)

            # 验证意图类别
            if intent not in INTENT_PRIORITY:
                logger.warning(f"意图识别结果无效: {intent}，降级为 chitchat")
                intent = "chitchat"

            # 计算置信度（简化处理：非闲聊即为高置信度）
            confidence = 0.9 if intent != "chitchat" else 0.7

            logger.info(f"意图识别完成 | message={message[:30]}... | intent={intent} | confidence={confidence}")
            return intent, confidence

        except Exception as e:
            logger.error(f"意图识别失败: {e}，降级为 chitchat")
            return "chitchat", 0.5

    def _extract_intent_from_text(self, text: str) -> str:
        """从LLM返回的文本中提取意图标签（修复 2.1：增强提取逻辑的健壮性）"""
        import re

        text_lower = text.lower().strip()
        valid_intents = ["product_inquiry", "policy_interpretation", "faq", "chitchat", "transfer_human"]

        # 1. 如果文本本身就是一个有效的意图标签，直接返回
        if text_lower in valid_intents:
            return text_lower

        # 2. 尝试匹配 "意图：xxx" 或 "意图:xxx" 格式（支持中英文冒号）
        match = re.search(r'意图[：:]\s*([\w_]+)', text)
        if match:
            intent = match.group(1).lower()
            if intent in valid_intents:
                return intent

        # 3. 尝试从文本中提取任意位置的有效意图标签（更宽松）
        for intent in valid_intents:
            # 使用单词边界匹配，避免部分匹配（如 "product" 匹配到 "product_inquiry"）
            pattern = r'\b' + re.escape(intent) + r'\b'
            if re.search(pattern, text_lower):
                return intent

        # 4. 尝试提取最后一个出现的有效意图（兜底策略）
        found_intents = []
        for intent in valid_intents:
            if intent in text_lower:
                found_intents.append(intent)

        if found_intents:
            # 返回最后出现的意图（假设 LLM 在末尾给出最终答案）
            return found_intents[-1]

        # 5. 无法提取，返回原文本（后续会校验是否为有效意图）
        logger.warning(f"无法从文本中提取有效意图: {text[:100]}...")
        return text_lower

    def get_knowledge_type(self, intent: str) -> Optional[str]:
        """获取意图对应的知识类型"""
        return INTENT_TO_KNOWLEDGE_TYPE.get(intent)

    # ═══════════════════════════════════════════════════════════════
    # 投顾意图分类（新增）
    # ═══════════════════════════════════════════════════════════════

    async def classify_advisor(self, message: str, history: Optional[list] = None) -> Tuple[str, float]:
        """
        投顾意图分类（4类：product_recommend / portfolio_analysis / asset_allocation / comparison）

        Args:
            message: 用户消息
            history: 对话历史（可选）
        Returns:
            (intent, confidence) 投顾意图类别和置信度
        """
        prompt = self.advisor_prompt_template.format(user_query=message)

        try:
            result = await self.llm.classify(prompt, temperature=0.1)
            intent = result.strip().lower()

            # 验证意图类别
            if intent not in ADVISOR_INTENT_PRIORITY:
                logger.warning(f"投顾意图识别结果无效: {intent}，降级为 product_recommend")
                intent = "product_recommend"

            # 置信度：显式匹配关键词加权重
            confidence = self._calc_advisor_confidence(intent, message)

            logger.info(
                f"投顾意图识别完成 | message={message[:30]}... | intent={intent} | confidence={confidence}"
            )
            return intent, confidence

        except Exception as e:
            logger.error(f"投顾意图识别失败: {e}，降级为 product_recommend")
            return "product_recommend", 0.5

    def _calc_advisor_confidence(self, intent: str, message: str) -> float:
        """计算投顾意图置信度（基于关键词匹配的启发式增强）"""
        keywords = {
            "product_recommend": ["推荐", "筛选", "找产品", "有什么好的", "挑", "选一只"],
            "portfolio_analysis": ["持仓", "集中度", "盈亏", "仓位", "行业分布", "分析"],
            "asset_allocation": ["配置", "比例", "分配", "怎么配", "资产配置", "仓位建议"],
            "comparison": ["对比", "比较", "差异", "不同", "vs"],
        }

        base_confidence = 0.80
        for kw in keywords.get(intent, []):
            if kw in message:
                base_confidence += 0.05  # 每个匹配关键词 +5%
        return min(base_confidence, 0.95)

    def get_agent_action(self, intent: str) -> Optional[str]:
        """获取投顾意图对应的 Agent 工具名"""
        return ADVISOR_INTENT_TO_AGENT_ACTION.get(intent)

    def is_advisor_intent(self, intent: str) -> bool:
        """判断是否为投顾意图"""
        return intent in ADVISOR_INTENT_PRIORITY


# 全局单例
_intent_service: Optional[IntentService] = None


def get_intent_service() -> IntentService:
    """获取意图识别服务单例"""
    global _intent_service
    if _intent_service is None:
        _intent_service = IntentService()
    return _intent_service
