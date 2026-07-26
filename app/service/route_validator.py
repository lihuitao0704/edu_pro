"""Deterministic validation for LLM/rule routing decisions."""

from __future__ import annotations

from app.model.route_decision import RouteDecision, RouteTask


AGENT_BY_INTENT = {
    "product_faq": "customer_service",
    "chitchat": "customer_service",
    "investment_recommendation": "advisor",
    "risk_control": "risk_monitor",
    "data_analysis": "nl2sql",
    "business_operation": "operator",
    "customer_account_query": "customer_account",
    "customer_risk_explanation": "customer_account",
    "customer_recommendation_explanation": "customer_account",
    "customer_transaction_guidance": "customer_account",
    "clarification": "router",
}

ROLE_ALLOWED_AGENTS = {
    "客户": {"customer_service", "advisor", "customer_account"},
    "理财顾问": {"customer_service", "advisor", "nl2sql", "operator"},
    "客户经理": {"customer_service", "advisor", "nl2sql", "operator"},
    "风控专员": {"customer_service", "risk_monitor", "nl2sql", "operator"},
    "管理员": {
        "customer_service",
        "advisor",
        "risk_monitor",
        "nl2sql",
        "operator",
    },
}


class RouteValidator:
    """Validate route legality without asking an LLM to judge its own output."""

    clarification_threshold = 0.70

    @staticmethod
    def _permission_message(user_role: str, decision: RouteDecision) -> str:
        """Return a role-aware, customer-friendly denial without exposing RBAC internals."""
        if user_role != "客户":
            return (
                f"抱歉，当前身份“{user_role}”暂不支持这项服务。"
                "如需继续处理，请联系管理员确认业务权限。"
            )
        if decision.target_agent == "nl2sql":
            return (
                "抱歉，为了保护客户隐私，我只能协助您查询本人账户相关信息。"
                "您可以试试：“查看我的风险等级”“查询我的持仓”"
                "或“查询我的交易记录”。"
            )
        if decision.target_agent == "risk_monitor":
            return (
                "抱歉，内部风控管理功能仅供工作人员使用。"
                "如果您想了解自己的账户风险，我可以协助查询风险等级和风险提示。"
            )
        return (
            "抱歉，这项功能目前仅供工作人员使用。"
            "我仍可以协助您查询本人账户、了解产品或获取适合您的配置建议。"
        )

    def validate(
        self,
        decision: RouteDecision,
        *,
        user_role: str,
        context: dict | None = None,
    ) -> RouteDecision:
        validated = decision.model_copy(deep=True)

        # A customer's operation wording expresses an intent, not authority to
        # invoke an employee-side write tool. Convert it to a safe transaction
        # draft/guidance flow instead of returning a blunt RBAC denial.
        if user_role == "客户" and (
            validated.task == RouteTask.EXECUTE
            or validated.target_agent == "operator"
        ):
            validated.intent = "customer_transaction_guidance"
            validated.target_agent = "customer_account"
            validated.requires_confirmation = False
            validated.validation_notes.append(
                "customer operation converted to transaction guidance"
            )

        expected_agent = AGENT_BY_INTENT.get(validated.intent)

        if expected_agent and expected_agent != validated.target_agent:
            validated.validation_notes.append(
                f"agent corrected: {validated.target_agent} -> {expected_agent}"
            )
            validated.target_agent = expected_agent

        allowed_agents = ROLE_ALLOWED_AGENTS.get(
            user_role, ROLE_ALLOWED_AGENTS["客户"]
        )
        if (
            validated.target_agent not in allowed_agents
            and validated.target_agent != "router"
        ):
            validated.blocked = True
            validated.block_reason = self._permission_message(user_role, validated)
            validated.validation_notes.append("role permission denied")
            return validated

        if (
            validated.task == RouteTask.EXECUTE
            and validated.target_agent == "operator"
        ):
            validated.requires_confirmation = True

        if validated.task == RouteTask.UNKNOWN:
            validated.needs_clarification = True

        if validated.confidence < self.clarification_threshold:
            validated.needs_clarification = True
            validated.validation_notes.append("confidence below threshold")

        if validated.needs_clarification:
            validated.intent = "clarification"
            validated.target_agent = "router"
            if not validated.clarification_question:
                validated.clarification_question = (
                    "我还不能确定你希望查询信息、获取分析建议，还是执行一项业务操作。"
                    "请补充说明你的目标。"
                )
            if not validated.clarification_choices:
                validated.clarification_choices = [
                    "查询明细或状态",
                    "分析并给出建议",
                    "执行具体业务操作",
                ]

        return validated


def get_route_validator() -> RouteValidator:
    return RouteValidator()
