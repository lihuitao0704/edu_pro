"""
Intent Service — 意图识别服务
基于 LLM 的意图分类：
  - 客服意图（5类）：product_inquiry / policy_interpretation / faq / chitchat / transfer_human
  - 投顾意图（4类）：product_recommend / portfolio_analysis / asset_allocation / comparison
"""

from typing import Optional, Tuple
from pathlib import Path
import re

from app.model.route_decision import (
    RouteDecision,
    RouteDomain,
    RoutePlan,
    RouteTask,
)
from app.tool.llm_tool import get_llm_tool
from app.utils.logger import get_logger

logger = get_logger("service.intent")
ROUTER_LLM_TIMEOUT_SECONDS = 4.0

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
    "clarification",
}

# Router 意图 → 分发目标 Agent
ROUTER_INTENT_TO_AGENT = {
    "product_faq": "customer_service",
    "chitchat": "customer_service",
    "investment_recommendation": "advisor",
    "risk_control": "risk_monitor",
    "data_analysis": "nl2sql",
    "business_operation": "operator",
    "clarification": "router",
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
    def _extract_route_entities(message: str) -> dict:
        """Extract only high-confidence entities; downstream agents may enrich them."""
        import re

        entities: dict = {}
        customer_id = re.search(
            r"客户(?:ID|编号)\s*(?:是|为|=|[:：])?\s*(\d+)",
            message,
            re.I,
        )
        if customer_id:
            entities["customer_id"] = int(customer_id.group(1))

        customer_name = re.search(
            r"客户(?:姓名|名称)?(?:为|是|叫)?\s*"
            r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9]{0,7})"
            r"(?=的|持仓|账户|工单|交易|[,，。；;\s]|$)",
            message,
        )
        if customer_name and customer_name.group(1) not in {
            "所有",
            "多少",
            "哪些",
            "查询",
        }:
            entities["customer_name"] = customer_name.group(1)

        amount = re.search(r"(\d+(?:\.\d+)?)\s*(万|万元|元)", message)
        if amount:
            value = float(amount.group(1))
            if amount.group(2) in {"万", "万元"}:
                value *= 10000
            entities["amount"] = int(value) if value.is_integer() else value

        for transaction_type in ("申购", "赎回", "转账", "开户"):
            if transaction_type in message:
                entities["transaction_type"] = transaction_type
                break
        return entities

    @staticmethod
    def _domain_for_message(message: str) -> RouteDomain:
        if re.search(r"(?<![A-Za-z0-9])[Rr][1-5](?![A-Za-z0-9])", message) and any(
            word in message for word in ("产品", "基金", "理财")
        ):
            return RouteDomain.PRODUCT
        if any(word in message for word in ("可疑", "风险", "风控", "预警", "异常")):
            return RouteDomain.RISK
        if "工单" in message:
            return RouteDomain.WORK_ORDER
        if any(word in message for word in ("持仓", "仓位", "组合", "行业分布", "集中度")):
            return RouteDomain.HOLDING
        if any(word in message for word in ("政策", "监管", "法规", "合规", "资管新规")):
            return RouteDomain.POLICY
        if any(
            word in message
            for word in ("申购", "赎回", "转账", "转到", "汇款", "交易", "手续费", "份额")
        ):
            return RouteDomain.TRANSACTION
        if any(word in message for word in ("产品", "基金", "理财", "收益率", "年化")):
            return RouteDomain.PRODUCT
        if any(word in message for word in ("客户", "用户", "画像", "AUM", "资产")):
            return RouteDomain.CUSTOMER
        return RouteDomain.GENERAL

    @staticmethod
    def _legacy_route(task: RouteTask, domain: RouteDomain) -> tuple[str, str]:
        if task == RouteTask.CHAT:
            return "chitchat", "customer_service"
        if task in {RouteTask.FAQ, RouteTask.TRANSFER_HUMAN}:
            return "product_faq", "customer_service"
        if task == RouteTask.RISK_CHECK or (
            task == RouteTask.QUERY and domain == RouteDomain.RISK
        ):
            return "risk_control", "risk_monitor"
        if task == RouteTask.QUERY:
            return "data_analysis", "nl2sql"
        if task in {RouteTask.ANALYZE, RouteTask.RECOMMEND}:
            return "investment_recommendation", "advisor"
        if task == RouteTask.EXECUTE:
            return "business_operation", "operator"
        return "clarification", "router"

    @classmethod
    def _build_route_decision(
        cls,
        message: str,
        task: RouteTask,
        domain: RouteDomain | None = None,
        *,
        confidence: float = 0.95,
        source: str = "rule",
        alternatives: list[str] | None = None,
        entities: dict | None = None,
    ) -> RouteDecision:
        domain = domain or cls._domain_for_message(message)
        intent, target_agent = cls._legacy_route(task, domain)
        return RouteDecision(
            request_text=message.strip(),
            intent=intent,
            task=task,
            domain=domain,
            target_agent=target_agent,
            confidence=confidence,
            decision_source=source,
            alternatives=alternatives or [],
            entities={**cls._extract_route_entities(message), **(entities or {})},
            requires_confirmation=task == RouteTask.EXECUTE,
        )

    @classmethod
    def _rule_route_decision(
        cls,
        message: str,
        *,
        context: dict | None = None,
    ) -> RouteDecision | None:
        """High-precision semantic rules. Ambiguous input is left to the LLM."""
        import re

        text = re.sub(r"\s+", "", message.strip())
        if not text:
            return cls._build_route_decision(
                message,
                RouteTask.UNKNOWN,
                RouteDomain.UNKNOWN,
                confidence=0.0,
            )

        pending = (context or {}).get("pending_route_decision")
        clarification_tasks = {
            "查询明细或状态": RouteTask.QUERY,
            "分析并给出建议": RouteTask.ANALYZE,
            "执行具体业务操作": RouteTask.EXECUTE,
        }
        if isinstance(pending, dict) and text in clarification_tasks:
            try:
                pending_domain = RouteDomain(
                    str(pending.get("domain") or "UNKNOWN").upper()
                )
            except ValueError:
                pending_domain = RouteDomain.UNKNOWN
            pending_entities = pending.get("entities")
            return cls._build_route_decision(
                message,
                clarification_tasks[text],
                pending_domain,
                confidence=1.0,
                source="clarification_choice",
                entities=pending_entities if isinstance(pending_entities, dict) else {},
            )

        if re.fullmatch(r"(你好|您好|嗨|哈喽|在吗|早上好|下午好|晚上好)[！!。.]?", text):
            return cls._build_route_decision(
                message, RouteTask.CHAT, RouteDomain.GENERAL
            )
        if any(word in text for word in ("写一首诗", "写首诗", "讲个笑话", "天气怎么样")):
            return cls._build_route_decision(
                message, RouteTask.CHAT, RouteDomain.GENERAL
            )
        if any(word in text for word in ("转人工", "人工客服", "找人工", "真人客服")):
            return cls._build_route_decision(
                message, RouteTask.TRANSFER_HUMAN, RouteDomain.GENERAL
            )

        if re.fullmatch(r"(确认|确定|好的|行|可以|同意|取消|放弃)[！!。.]?", text):
            last_agent = (context or {}).get("last_agent")
            last_intent = (context or {}).get("last_intent")
            if last_agent == "operator" or last_intent == "business_operation":
                return cls._build_route_decision(
                    message,
                    RouteTask.EXECUTE,
                    RouteDomain.TRANSACTION,
                    confidence=1.0,
                    source="context_rule",
                )
            return cls._build_route_decision(
                message,
                RouteTask.UNKNOWN,
                RouteDomain.GENERAL,
                confidence=0.45,
                source="context_rule",
                alternatives=["继续上一项业务操作", "普通对话确认"],
            )

        current_entities = cls._extract_route_entities(message)
        previous_entities = (context or {}).get("entities", {})
        inherited_customer_id = (
            current_entities.get("customer_id")
            or (
                previous_entities.get("customer_id")
                if isinstance(previous_entities, dict)
                else None
            )
        )
        is_advisor_followup = (
            (context or {}).get("last_agent") == "advisor"
            or (context or {}).get("last_intent") == "investment_recommendation"
        )
        if (
            inherited_customer_id
            and current_entities.get("amount") is not None
            and (
                is_advisor_followup
                or "投资" in text
                or any(word in text for word in ("这个客户", "该客户", "他要", "她要"))
            )
            and not any(word in text for word in ("申购", "赎回", "转账", "购买"))
        ):
            return cls._build_route_decision(
                message,
                RouteTask.RECOMMEND,
                RouteDomain.PRODUCT,
                confidence=0.98,
                source="context_rule",
                entities={
                    **(
                        previous_entities
                        if isinstance(previous_entities, dict)
                        else {}
                    ),
                    **current_entities,
                    "customer_id": int(inherited_customer_id),
                },
            )

        # R1-R5 here is a product attribute, not a risk-monitoring request.
        if (
            re.search(r"(?<![A-Za-z0-9])[Rr][1-5](?![A-Za-z0-9])", text)
            and any(word in text for word in ("产品", "基金", "理财"))
            and any(word in text for word in ("查询", "查", "筛选", "列出", "哪些", "所有"))
        ):
            level = re.search(
                r"(?<![A-Za-z0-9])([Rr][1-5])(?![A-Za-z0-9])",
                text,
            )
            return cls._build_route_decision(
                message,
                RouteTask.QUERY,
                RouteDomain.PRODUCT,
                entities={"risk_level": level.group(1).upper()} if level else {},
            )

        # A report changes system state; a check only inspects risk.
        if re.search(r"(上报|提交|登记).{0,6}(可疑|异常)", text):
            return cls._build_route_decision(
                message, RouteTask.EXECUTE, RouteDomain.RISK
            )
        if re.search(
            r"(核查|检测|识别|排查|监测|查看|查询|查一下|查下|有没有).{0,10}(可疑|异常|风险|预警)"
            r"|(可疑|异常|风险|预警).{0,10}(核查|检测|识别|排查|监测|记录)",
            text,
        ):
            return cls._build_route_decision(
                message, RouteTask.RISK_CHECK, RouteDomain.RISK
            )

        # Explanatory qualifiers override a bare financial operation noun.
        informational = (
            "手续费",
            "费率",
            "规则",
            "多久",
            "怎么收",
            "如何计算",
            "是什么",
            "有什么要求",
            "有什么区别",
            "是否支持",
            "确认时间",
        )
        financial_terms = (
            "产品",
            "基金",
            "理财",
            "申购",
            "赎回",
            "转账",
            "收益",
            "年化",
            "监管",
            "政策",
            "服务",
        )
        if any(word in text for word in informational) and any(
            word in text for word in financial_terms
        ):
            return cls._build_route_decision(message, RouteTask.FAQ)

        # Read-only structured queries must not be swallowed by advisor/operator.
        if "工单" in text and any(
            word in text for word in ("查询", "查", "进度", "状态", "列表", "哪些")
        ):
            return cls._build_route_decision(
                message, RouteTask.QUERY, RouteDomain.WORK_ORDER
            )
        query_markers = (
            "查询",
            "查一下",
            "查下",
            "列出",
            "列表",
            "明细",
            "记录",
            "所有",
            "多少",
            "统计",
            "排名",
            "趋势",
            "占比",
            "平均",
            "超过",
            "低于",
        )
        query_domains = (
            "客户",
            "用户",
            "产品",
            "持仓",
            "交易",
            "资产",
            "收益",
            "工单",
            "画像",
            "流水",
        )
        if any(word in text for word in query_markers) and any(
            word in text for word in query_domains
        ):
            return cls._build_route_decision(message, RouteTask.QUERY)

        if any(
            word in text
            for word in (
                "推荐",
                "筛选",
                "找产品",
                "配置建议",
                "资产配置",
                "怎么配置",
                "如何配置",
            )
        ):
            return cls._build_route_decision(message, RouteTask.RECOMMEND)
        if any(
            word in text
            for word in ("持仓分析", "分析持仓", "行业分布", "集中度", "仓位建议", "投资组合")
        ) or (
            "持仓" in text and any(word in text for word in ("分析", "建议", "诊断", "评估"))
        ):
            return cls._build_route_decision(message, RouteTask.ANALYZE)
        if any(word in text for word in ("对比", "比较")) and any(
            word in text for word in ("产品", "客户", "基金", "持仓", "组合")
        ):
            return cls._build_route_decision(message, RouteTask.ANALYZE)

        explicit_operations = (
            "创建工单",
            "关闭工单",
            "处理工单",
            "更新手机",
            "更新邮箱",
            "修改联系方式",
            "风评重做",
            "重新风险评估",
            "确认购买",
            "批量更新",
            "批量评估",
        )
        operation_terms = ("申购", "赎回", "转账给", "转到", "转出", "开户", "购买")
        action_markers = (
            "我要",
            "我想",
            "帮我",
            "请帮",
            "给客户",
            "替客户",
            "立即",
            "马上",
            "办理",
            "执行",
        )
        has_specific_parameter = bool(
            re.search(r"\d+\s*(?:万|万元|元|份)", text)
            or re.search(r"客户(?:ID|编号)?\s*\d+", text, re.I)
        )
        if any(word in text for word in explicit_operations) or (
            any(word in text for word in operation_terms)
            and (
                any(word in text for word in action_markers)
                or has_specific_parameter
                or text.startswith(("申购", "赎回", "转账", "开户"))
            )
        ):
            return cls._build_route_decision(message, RouteTask.EXECUTE)

        if any(
            word in text
            for word in ("监管政策", "最新政策", "资管新规", "了解一下", "有什么年化", "有什么理财")
        ):
            return cls._build_route_decision(message, RouteTask.FAQ)
        return None

    @classmethod
    def _keyword_quick_route(cls, message: str) -> Optional[tuple]:
        """Backward-compatible tuple view of the deterministic rule decision."""
        decision = cls._rule_route_decision(message)
        if decision is None or decision.task == RouteTask.UNKNOWN:
            return None
        logger.info(
            "Router确定性规则命中: task=%s domain=%s intent=%s",
            decision.task.value,
            decision.domain.value,
            decision.intent,
        )
        return decision.intent, decision.confidence, decision.legacy_params()

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
        text_lower = text.lower()
        for intent in ROUTER_INTENTS:
            if intent in text_lower:
                return intent
        return "clarification"

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

        return "clarification"

    @classmethod
    def _parse_supervisor_decision(
        cls,
        text: str,
        message: str,
    ) -> RouteDecision:
        import json
        import re

        cleaned = cls._strip_reasoning(text)
        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if not match:
                raise ValueError("LLM route response contains no JSON object")
            data = json.loads(match.group())

        try:
            task = RouteTask(str(data.get("task", "UNKNOWN")).upper())
        except ValueError:
            task = RouteTask.UNKNOWN
        try:
            domain = RouteDomain(str(data.get("domain", "UNKNOWN")).upper())
        except ValueError:
            domain = cls._domain_for_message(message)

        raw_confidence = data.get("confidence", 0.0)
        try:
            confidence = max(0.0, min(float(raw_confidence), 0.89))
        except (TypeError, ValueError):
            confidence = 0.0

        supplied_entities = data.get("entities")
        if not isinstance(supplied_entities, dict):
            supplied_entities = data.get("params")
        if not isinstance(supplied_entities, dict):
            supplied_entities = {}
        entities = {
            **cls._extract_route_entities(message),
            **{key: value for key, value in supplied_entities.items() if value is not None},
        }
        alternatives = data.get("alternatives")
        if not isinstance(alternatives, list):
            alternatives = []

        decision = cls._build_route_decision(
            message,
            task,
            domain,
            confidence=confidence,
            source="llm_supervisor",
            alternatives=[str(item) for item in alternatives[:2]],
            entities=entities,
        )
        if task == RouteTask.UNKNOWN or confidence < 0.70:
            decision.needs_clarification = True
            decision.clarification_question = str(
                data.get("clarification_question")
                or "你希望查询信息、获取分析建议，还是执行一项具体业务？"
            )
        return decision

    async def decide_route(
        self,
        message: str,
        *,
        user_role: str = "客户",
        context: dict | None = None,
    ) -> RouteDecision:
        """Return one reusable top-level route decision for the whole request."""
        rule_decision = self._rule_route_decision(message, context=context)
        if rule_decision is not None:
            logger.info(
                "Router规则决策 | task=%s | domain=%s | intent=%s",
                rule_decision.task.value,
                rule_decision.domain.value,
                rule_decision.intent,
            )
            return rule_decision

        prompt = self._load_prompt("router_intent.txt", self._default_router_prompt)
        context = context or {}
        context_summary = {
            "last_intent": context.get("last_intent"),
            "last_agent": context.get("last_agent"),
            "entities": context.get("entities", {}),
        }
        try:
            import asyncio

            prompt_text = prompt.format(
                user_message=message,
                user_role=user_role,
                context_summary=str(context_summary),
            )
            result = await asyncio.wait_for(
                self.llm.classify(
                    prompt_text, temperature=0.1, max_tokens=320
                ),
                timeout=ROUTER_LLM_TIMEOUT_SECONDS,
            )
            decision = self._parse_supervisor_decision(result.strip(), message)
            logger.info(
                "Router LLM决策 | task=%s | domain=%s | confidence=%.2f",
                decision.task.value,
                decision.domain.value,
                decision.confidence,
            )
            return decision
        except Exception as exc:
            logger.error(
                "Router LLM分类失败: %s: %s，转为澄清",
                type(exc).__name__,
                str(exc)[:120],
            )
            decision = self._build_route_decision(
                message,
                RouteTask.UNKNOWN,
                self._domain_for_message(message),
                confidence=0.0,
                source="fallback",
            )
            decision.needs_clarification = True
            decision.clarification_question = (
                "我暂时无法准确判断你的目标。请说明你是想查询信息、"
                "获取分析建议，还是执行具体业务操作。"
            )
            return decision

    @staticmethod
    def _split_compound_message(message: str) -> list[str]:
        """Split explicit compound requests while keeping ordinary prose intact."""
        import re

        normalized = message.strip()
        for connector in ("顺便", "同时", "然后", "另外", "并且", "接着"):
            normalized = normalized.replace(connector, "，")
        normalized = re.sub(
            r"再(?=(?:帮我|请|查询|查|推荐|分析|核查|检测|上报|创建|申购|赎回|转账))",
            "，",
            normalized,
        )
        normalized = re.sub(r"[,，]{2,}", "，", normalized)
        clauses = [
            clause.strip(" \t\r\n,，。；;")
            for clause in re.split(r"[,，；;。]+", normalized)
        ]
        return [clause for clause in clauses if clause][:4]

    async def plan_route(
        self,
        message: str,
        *,
        user_role: str = "客户",
        context: dict | None = None,
    ) -> RoutePlan:
        """Build a bounded multi-intent plan, falling back to a single decision."""
        clauses = self._split_compound_message(message)
        if len(clauses) <= 1:
            decision = await self.decide_route(
                message, user_role=user_role, context=context
            )
            return RoutePlan(
                original_message=message,
                tasks=[decision],
                execution_mode="single",
                decision_source=decision.decision_source,
            )

        decisions = [
            await self.decide_route(
                clause,
                user_role=user_role,
                context=context,
            )
            for clause in clauses
        ]
        non_chat = [
            decision
            for decision in decisions
            if decision.task != RouteTask.CHAT
        ]
        global_entities = self._extract_route_entities(message)

        # A fragment such as "我有50万" is context for the one actionable task,
        # not a second intent that needs clarification.
        actionable = [
            decision
            for decision in non_chat
            if not (
                decision.task == RouteTask.UNKNOWN
                and bool(decision.entities)
            )
        ]
        ready = [
            decision
            for decision in actionable
            if decision.task != RouteTask.UNKNOWN
        ]
        if len(ready) == 1 and len(actionable) <= 1:
            decision = ready[0]
            decision.entities = {**global_entities, **decision.entities}
            return RoutePlan(
                original_message=message,
                tasks=[decision],
                execution_mode="single",
                decision_source="compound_context",
            )

        if len(actionable) < 2:
            decision = await self.decide_route(
                message, user_role=user_role, context=context
            )
            return RoutePlan(
                original_message=message,
                tasks=[decision],
                execution_mode="single",
                decision_source=decision.decision_source,
            )

        has_write = any(
            decision.task == RouteTask.EXECUTE for decision in actionable
        )
        return RoutePlan(
            original_message=message,
            tasks=actionable,
            execution_mode=(
                "mixed_requires_confirmation" if has_write else "safe_sequential"
            ),
            decision_source="compound_split",
        )

    async def classify_router(
        self,
        message: str,
        *,
        user_role: str = "客户",
        context: dict | None = None,
    ) -> Tuple[str, float, dict]:
        """Backward-compatible tuple API backed by :meth:`decide_route`."""
        decision = await self.decide_route(
            message, user_role=user_role, context=context
        )
        return decision.intent, decision.confidence, decision.legacy_params()

    @staticmethod
    def _default_router_prompt() -> str:
        """Router 分类默认 Prompt（文件缺失时的兜底）"""
        return """你是金融财富助手的路由监督器。请同时识别任务类型和业务领域。

任务类型：CHAT, FAQ, QUERY, ANALYZE, RECOMMEND, EXECUTE, RISK_CHECK,
TRANSFER_HUMAN, UNKNOWN。
业务领域：GENERAL, PRODUCT, HOLDING, TRANSACTION, CUSTOMER, WORK_ORDER,
RISK, POLICY, UNKNOWN。

区分语义动作：
- “赎回手续费怎么收”是 FAQ；“帮我赎回10万元”是 EXECUTE。
- “核查可疑交易”是 RISK_CHECK；“上报可疑交易”是 EXECUTE。
- “查询持仓明细”是 QUERY；“分析持仓并给建议”是 ANALYZE。
- 无法可靠区分时输出 UNKNOWN，不得默认成 FAQ。

只输出JSON：
{{"task":"QUERY","domain":"HOLDING","confidence":0.85,
"alternatives":[],"entities":{{"customer_name":null,"customer_id":null,
"product_name":null,"amount":null,"transaction_type":null}},
"clarification_question":null}}

用户身份：{user_role}
会话上下文：{context_summary}
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
