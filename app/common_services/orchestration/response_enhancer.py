from app.common_services.context_manager.models import AgentResult


class ResponseEnhancer:
    _GUIDANCE = (
        "\n\n为了给您提供更合适的参考，请补充：\n"
        "1. 投资期限\n2. 风险偏好\n3. 投资金额"
    )
    _QUESTIONS = ["稳健型理财有哪些？", "R3风险产品有哪些？", "基金和债券如何选择？"]

    def enhance(self, result: AgentResult) -> AgentResult:
        needs_guidance = (
            result.intent == "investment_recommendation"
            and (result.confidence < 0.65 or result.source_count == 0 or result.fallback_used)
        )
        if needs_guidance:
            result.reply = result.reply.rstrip() + self._GUIDANCE
            result.suggested_questions = list(self._QUESTIONS)
        return result
