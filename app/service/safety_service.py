"""
Safety Service — 安全审核服务
内容合规检测 + 置信度判断
"""

import re
from typing import Optional
from pydantic import BaseModel

from app.utils.logger import get_logger

logger = get_logger("service.safety")


class SafetyCheckResult(BaseModel):
    """安全审核结果"""
    passed: bool
    reason: Optional[str] = None
    action: Optional[str] = None  # replace_with_safe_response


class SafetyService:
    """安全审核服务"""

    # 违规内容正则模式 — 扩充至50+模式（覆盖承诺类/夸大类/诱导类/违规类）
    PROHIBITED_PATTERNS = [
        # ── 承诺类 ──
        r"零风险", r"稳赚不赔", r"无风险.*理财",
        r"绝对.*赚", r"一定.*涨", r"包赚", r"肯定.*能赚",
        r"保证.*收益", r"承诺.*回报", r"稳赚", r"零损失",
        r"保本.*高收益", r"无风险.*收益",
        # ── 夸大类 ──
        r"最高.*收益", r"最佳.*产品", r"第一.*名",
        r"绝对.*安全", r"100%.*收益", r"稳如泰山",
        r"万无一失", r"只赚不赔",
        # ── 诱导类 ──
        r"内幕消息", r"代客操作", r"代客理财",
        r"立即.*抢购", r"限时.*优惠", r"错过.*再等",
        r"内部.*渠道", r"特殊.*名额",
        # ── 违规类 ──
        r"洗钱", r"逃税", r"避税", r"套现",
        r"非法集资", r"庞氏骗局", r"传销",
        # ── 金融合规类 ──
        r"刚性兑付", r"兜底", r"暗箱操作",
        r"老鼠仓", r"利益输送",
    ]

    # 用户输入敏感词（前端+后端双重过滤，阻断恶意输入发给LLM）
    USER_INPUT_BLOCKED = [
        r"(操你|fuck|shit|damn|傻逼|脑残|sb|cnm|tmd|nmsl)",
        r"(hack|攻击|漏洞|注入|exploit|inject|script|alert|onerror)",
        r"(自杀|杀人|毒品|赌博|porn|色情)",
    ]

    # 需要上下文判断的"敏感词"模式
    CONTEXTUAL_PATTERNS = [
        (r"保本保息", r"(不|没有|无|不存在|无法|不能|不会|非).{0,10}保本保息"),
        (r"保证收益", r"(不|没有|无|不存在|无法|不能|不会).{0,10}保证收益"),
        (r"承诺收益|收益承诺", r"(不|没有|无|不存在|无法|不能|不会|不代表|不构成).{0,10}(承诺收益|收益承诺)"),
        (r"稳赚", r"(不|没有|无|并非|不能).{0,10}稳赚"),
        (r"高收益", r"(风险|波动|可能|不一定).{0,10}高收益"),
    ]

    # 兜底话术
    FALLBACK_MESSAGE = "抱歉，我暂时无法回答这个问题。建议您拨打客服热线400-XXX-XXXX咨询人工客服，我们的理财顾问将竭诚为您服务。"
    # 输入违规话术
    INPUT_BLOCKED_MESSAGE = "您的输入包含不当内容，请使用文明用语。如有业务问题，请重新描述。"

    async def filter_user_input(self, text: str) -> tuple[bool, Optional[str]]:
        """
        过滤用户输入中的敏感/恶意内容。

        Returns:
            (is_safe, blocked_reason) — is_safe=True表示通过，False表示需拦截
        """
        import re
        for pattern in self.USER_INPUT_BLOCKED:
            if re.search(pattern, text, re.IGNORECASE):
                logger.warning(f"用户输入被拦截 | pattern={pattern[:30]}... | text={text[:50]}...")
                return False, self.INPUT_BLOCKED_MESSAGE
        return True, None

    async def check_content(self, text: str) -> SafetyCheckResult:
        """
        审核 LLM 输出内容

        Args:
            text: 待审核文本（可能是纯文本或 JSON 格式）
        Returns:
            SafetyCheckResult
        """
        import json

        # 尝试解析 JSON，提取 reply 字段进行审核
        content_to_check = text
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "reply" in data:
                content_to_check = data["reply"]
        except (json.JSONDecodeError, TypeError):
            # 不是 JSON，直接审核原文本
            pass

        # 1. 检查绝对违规模式（直接拦截）
        for pattern in self.PROHIBITED_PATTERNS:
            if re.search(pattern, content_to_check):
                logger.warning(f"安全审核不通过 | 包含违规内容: {pattern} | text={content_to_check[:50]}...")
                return SafetyCheckResult(
                    passed=False,
                    reason=f"包含违规内容：{pattern}",
                    action="replace_with_safe_response",
                )

        # 2. 检查上下文敏感模式（否定语境下不拦截）
        for sensitive_pattern, negation_pattern in self.CONTEXTUAL_PATTERNS:
            if re.search(sensitive_pattern, content_to_check):
                # 敏感词出现了，检查是否在否定语境中
                if not re.search(negation_pattern, content_to_check):
                    # 不在否定语境中，判定为违规
                    logger.warning(f"安全审核不通过 | 包含敏感内容: {sensitive_pattern} | full_text={content_to_check}")
                    return SafetyCheckResult(
                        passed=False,
                        reason=f"包含敏感内容：{sensitive_pattern}",
                        action="replace_with_safe_response",
                    )
                # 在否定语境中（如"不存在保证收益"），合规，跳过

        return SafetyCheckResult(passed=True)

    async def check_confidence(self, rag_results: list, intent_confidence: float) -> dict:
        """
        综合置信度判断

        Args:
            rag_results: RAG 检索结果列表
            intent_confidence: 意图识别置信度
        Returns:
            {"should_fallback": bool, "reason": str, "message": str}
        """
        # RAG 检索最高分
        rag_max_score = max([r.get("score", 0) for r in rag_results], default=0)

        # RAG 置信度过低（阈值从 0.6 降到 0.3，配合向量直排策略）
        if rag_max_score < 0.3:
            logger.warning(f"RAG 置信度过低 | max_score={rag_max_score:.3f}")
            return {
                "should_fallback": True,
                "reason": "知识检索置信度过低",
                "message": "该问题需要人工客服进一步确认",
            }

        # 意图识别置信度过低
        if intent_confidence < 0.5:
            logger.warning(f"意图识别置信度过低 | confidence={intent_confidence:.3f}")
            return {
                "should_fallback": True,
                "reason": "意图识别置信度过低",
                "message": "抱歉，我没有完全理解您的问题，请换一种方式描述",
            }

        return {"should_fallback": False}


# 全局单例
_safety_service: Optional[SafetyService] = None


def get_safety_service() -> SafetyService:
    """获取安全审核服务单例"""
    global _safety_service
    if _safety_service is None:
        _safety_service = SafetyService()
    return _safety_service
