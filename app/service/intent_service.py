"""
Intent Service — 意图识别服务
基于 LLM 的意图分类（5类：product_inquiry / policy_interpretation / faq / chitchat / transfer_human）
"""

from typing import Optional, Tuple
from pathlib import Path

from app.tool.llm_tool import get_llm_tool
from app.utils.logger import get_logger

logger = get_logger("service.intent")

# 意图优先级（用于多意图场景）
INTENT_PRIORITY = {
    "transfer_human": 5,
    "faq": 4,
    "product_inquiry": 3,
    "policy_interpretation": 2,
    "chitchat": 1,
}

# 意图到知识类型映射
INTENT_TO_KNOWLEDGE_TYPE = {
    "product_inquiry": "product_knowledge",
    "policy_interpretation": "policy_knowledge",
    "faq": "faq_knowledge",
}


class IntentService:
    """意图识别服务"""

    def __init__(self):
        self.llm = get_llm_tool()
        self.prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        """加载意图识别 Prompt 模板"""
        prompt_path = Path(__file__).parent.parent / "prompts" / "intent_classify.txt"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        else:
            logger.warning(f"意图识别 Prompt 文件不存在: {prompt_path}，使用默认模板")
            return self._default_prompt()

    def _default_prompt(self) -> str:
        """默认意图识别 Prompt"""
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
            intent = result.strip().lower()

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

    def get_knowledge_type(self, intent: str) -> Optional[str]:
        """获取意图对应的知识类型"""
        return INTENT_TO_KNOWLEDGE_TYPE.get(intent)


# 全局单例
_intent_service: Optional[IntentService] = None


def get_intent_service() -> IntentService:
    """获取意图识别服务单例"""
    global _intent_service
    if _intent_service is None:
        _intent_service = IntentService()
    return _intent_service
