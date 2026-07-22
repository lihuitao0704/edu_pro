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

    # 违规内容正则模式
    # 匹配"承诺性"表述，但排除 LLM 在否定/解释/风险提示中提到的情况
    # 例如：LLM 说"不存在保证收益的产品"是合规的，不应被拦截
    PROHIBITED_PATTERNS = [
        r"保本保息",          # 保本保息 — 违规承诺
        r"零风险",            # 零风险 — 违规表述
        r"稳赚不赔",          # 稳赚不赔 — 违规表述
        r"无风险.*理财",      # 无风险理财 — 违规表述
        r"绝对.*赚",          # 绝对赚 — 违规表述
        r"一定.*涨",          # 一定涨 — 违规表述
        r"包赚",              # 包赚 — 违规表述
        r"肯定.*能赚",        # 肯定能赚 — 违规表述
    ]

    # 需要上下文判断的"敏感词"模式
    # 这些词本身不一定违规，需要看上下文（是否被否定/解释）
    CONTEXTUAL_PATTERNS = [
        (r"保证收益", r"(不|没有|无|不存在|无法|不能|不会).{0,10}保证收益"),
        (r"承诺.*收益", r"(不|没有|无|不存在|无法|不能|不会).{0,10}承诺.{0,5}收益"),
    ]

    # 兜底话术
    FALLBACK_MESSAGE = "抱歉，我暂时无法回答这个问题。建议您拨打客服热线400-XXX-XXXX咨询人工客服，我们的理财顾问将竭诚为您服务。"

    async def check_content(self, text: str) -> SafetyCheckResult:
        """
        审核 LLM 输出内容

        Args:
            text: 待审核文本
        Returns:
            SafetyCheckResult
        """
        # 1. 检查绝对违规模式（直接拦截）
        for pattern in self.PROHIBITED_PATTERNS:
            if re.search(pattern, text):
                logger.warning(f"安全审核不通过 | 包含违规内容: {pattern} | text={text[:50]}...")
                return SafetyCheckResult(
                    passed=False,
                    reason=f"包含违规内容：{pattern}",
                    action="replace_with_safe_response",
                )

        # 2. 检查上下文敏感模式（否定语境下不拦截）
        for sensitive_pattern, negation_pattern in self.CONTEXTUAL_PATTERNS:
            if re.search(sensitive_pattern, text):
                # 敏感词出现了，检查是否在否定语境中
                if not re.search(negation_pattern, text):
                    # 不在否定语境中，判定为违规
                    logger.warning(f"安全审核不通过 | 包含敏感内容: {sensitive_pattern} | text={text[:50]}...")
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
