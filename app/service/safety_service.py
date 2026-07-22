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
    PROHIBITED_PATTERNS = [
        r"保证收益",
        r"保本保息",
        r"零风险",
        r"稳赚不赔",
        r"承诺.*收益",
        r"无风险.*理财",
        r"绝对.*赚",
        r"一定.*涨",
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
        for pattern in self.PROHIBITED_PATTERNS:
            if re.search(pattern, text):
                logger.warning(f"安全审核不通过 | 包含违规内容: {pattern} | text={text[:50]}...")
                return SafetyCheckResult(
                    passed=False,
                    reason=f"包含违规内容：{pattern}",
                    action="replace_with_safe_response",
                )

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

        # RAG 置信度过低
        if rag_max_score < 0.6:
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
