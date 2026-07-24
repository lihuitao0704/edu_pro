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

# ── Router 统一意图（6类）──
ROUTER_INTENTS = {
    "product_faq",
    "investment_recommendation",
    "risk_control",
    "data_analysis",
    "business_operation",
    "chitchat",
}

# 关键词快速通道：命中关键词直接判定意图，无需调用LLM
ROUTER_KEYWORD_MAP = [
    # (关键词列表, 意图)
    (["申购", "赎回", "转账给", "开户", "更新手机", "更新邮箱", "风评重做",
      "创建工单", "上报可疑"], "business_operation"),
    (["推荐", "筛选", "找产品", "有什么好", "配置建议", "仓位", "持仓分析",
      "集中度", "行业分布", "对比", "比较", "资产配置"], "investment_recommendation"),
    (["异常", "可疑交易", "风险检测", "风控标记", "风险监测"], "risk_control"),
    (["统计", "排名", "趋势", "多少客户", "占比", "分析数据", "查询数据",
      "本月", "上月", "本季度"], "data_analysis"),
]

# Router 意图 → 分发目标 Agent
ROUTER_INTENT_TO_AGENT = {
    "product_faq": "customer_service",
    "chitchat": "customer_service",
    "investment_recommendation": "advisor",
    "risk_control": "risk_monitor",
    "data_analysis": "nl2sql",
    "business_operation": "operator",
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

    # ═══════════════════════════════════════════════════════════════
    # Router 统一意图分类（6类）
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _keyword_quick_route(message: str) -> Optional[tuple]:
        """关键词快速通道：命中明显关键词时跳过LLM分类，节省延迟。

        Returns:
            (intent, confidence, params) 或 None（未命中）
        """
        for keywords, intent in ROUTER_KEYWORD_MAP:
            for kw in keywords:
                if kw in message:
                    logger.info(f"Router关键词快速命中: {kw} → {intent}")
                    return (intent, 0.95, {"customer_name": None, "customer_id": None,
                                           "product_name": None, "amount": None,
                                           "transaction_type": None})
        return None

    @staticmethod
    def _extract_router_params(text: str) -> dict:
        """从LLM返回的JSON文本中提取参数"""
        import json
        import re

        default_params = {"customer_name": None, "customer_id": None,
                          "product_name": None, "amount": None,
                          "transaction_type": None}
        try:
            # 先剥离推理/思考文本
            cleaned = IntentService._strip_reasoning(text)
            # 尝试直接解析JSON
            data = json.loads(cleaned)
            params = data.get("params", {})
            result = {}
            for k in default_params:
                result[k] = params.get(k)
            return result
        except (json.JSONDecodeError, TypeError):
            pass

        # 兜底：从文本中提取 JSON 对象再解析
        try:
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                data = json.loads(json_match.group())
                params = data.get("params", {})
                result = {}
                for k in default_params:
                    result[k] = params.get(k)
                return result
        except (json.JSONDecodeError, TypeError):
            pass

        return default_params

    @staticmethod
    def _strip_reasoning(text: str) -> str:
        """剥离 LLM 输出中的推理/思考文本，保留 JSON 部分"""
        import re
        text = text.strip()
        # 移除常见推理前缀（如 "思考过程：..."、"让我分析..."、"分析：" 等）
        text = re.sub(r'^(?:思考过程|分析过程|推理过程|思考|分析|推理|让我分析|我来分析|让我思考)[^\{}\n]*[:：]?\s*', '', text)
        # 移除 "我们被要求..." 等元描述前缀
        text = re.sub(r'^(?:我们被要求|我需要|根据要求)[^\{}\n]*\n+', '', text)
        return text.strip()

    @staticmethod
    def _regex_extract_intent(text: str) -> str:
        """从文本中用正则提取意图（兜底方案）"""
        import re
        text_lower = text.lower()
        # 直接搜索意图关键词
        for intent in ROUTER_INTENTS:
            if intent in text_lower:
                return intent
        return "product_faq"

    @staticmethod
    def _extract_router_intent(text: str) -> str:
        """从LLM返回文本中提取意图标签"""
        import re
        import json

        # 先剥离推理/思考文本
        text = IntentService._strip_reasoning(text)
        text_clean = text.strip()

        # 1. 尝试JSON解析
        try:
            data = json.loads(text_clean)
            intent = data.get("intent", "")
            if intent in ROUTER_INTENTS:
                return intent
        except (json.JSONDecodeError, TypeError):
            pass

        # 2. 尝试匹配 "intent": "xxx" 模式
        match = re.search(r'"intent"\s*:\s*"([^"]+)"', text_clean)
        if match:
            intent = match.group(1)
            if intent in ROUTER_INTENTS:
                return intent

        # 3. 从文本中提取有效意图标识符
        for intent in ROUTER_INTENTS:
            if intent in text_clean.lower():
                return intent

        return "product_faq"  # 最终兜底

    async def classify_router(self, message: str) -> Tuple[str, float, dict]:
        """Router Agent 统一意图分类（6类）

        流程：关键词快速通道 → LLM分类 → 意图提取 + 参数提取

        Returns:
            (intent, confidence, params_dict)
        """
        # 1. 关键词快速通道
        quick = self._keyword_quick_route(message)
        if quick:
            return quick

        # 2. 加载Router分类 Prompt
        prompt = self._load_prompt("router_intent.txt", self._default_router_prompt)

        # 3. 调用LLM
        try:
            prompt_text = prompt.format(user_message=message)
            result = await self.llm.classify(prompt_text, temperature=0.1, max_tokens=256)
            result = result.strip()

            # 调试日志：打印 LLM 原始输出（替换换行符避免日志格式混乱）
            result_display = result.replace('\n', '\\n')[:200]
            logger.info(f"Router LLM 原始输出 | len={len(result)} | text={result_display}...")

            # 4. 提取意图（容错：单步异常不中断）
            try:
                intent = self._extract_router_intent(result)
            except Exception as e:
                logger.warning(f"Router 意图提取异常: {type(e).__name__}: {e}，尝试正则兜底")
                intent = self._regex_extract_intent(result)

            # 5. 提取参数（容错）
            try:
                params = self._extract_router_params(result)
            except Exception as e:
                logger.warning(f"Router 参数提取异常: {type(e).__name__}: {e}，使用默认参数")
                params = {"customer_name": None, "customer_id": None,
                          "product_name": None, "amount": None,
                          "transaction_type": None}

            # 6. 置信度
            confidence = 0.90 if intent != "chitchat" else 0.75

            logger.info(f"Router分类完成 | message={message[:40]}... | intent={intent} | confidence={confidence}")
            return intent, confidence, params

        except Exception as e:
            logger.error(f"Router分类失败: {type(e).__name__}: {str(e)[:100]}，兜底为 product_faq")
            return "product_faq", 0.5, {"customer_name": None, "customer_id": None,
                                         "product_name": None, "amount": None,
                                         "transaction_type": None}

    @staticmethod
    def _default_router_prompt() -> str:
        """Router 分类默认 Prompt（文件缺失时的兜底）"""
        return """你是金融智能服务平台的路由分类器。请将用户消息分类到以下6种意图之一，并提取关键参数。

6种意图：
- product_faq：产品咨询、FAQ、规则说明、问候
- investment_recommendation：推荐产品、资产配置、持仓分析、客户对比
- risk_control：异常交易、风险识别、合规检查、可疑上报
- data_analysis：数据统计、收益分析、用户分析
- business_operation：申购、赎回、转账、开户、信息更新
- chitchat：纯闲聊（与金融业务完全无关）

输出格式（仅输出 JSON，无其他内容）：
{{"intent": "意图标识符", "confidence": 0.90, "params": {{"customer_name": null, "customer_id": null, "product_name": null, "amount": null, "transaction_type": null}}}}

用户输入："{user_message}"

JSON："""

    @staticmethod
    def get_router_agent(intent: str) -> str:
        """获取Router意图对应的目标Agent名称"""
        return ROUTER_INTENT_TO_AGENT.get(intent, "customer_service")


# 全局单例
_intent_service: Optional[IntentService] = None


def get_intent_service() -> IntentService:
    """获取意图识别服务单例"""
    global _intent_service
    if _intent_service is None:
        _intent_service = IntentService()
    return _intent_service
