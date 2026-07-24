import re

from app.common_services.safety_guard.risk_rule import OUTPUT_RULES


class OutputSafetyDecision:
    def __init__(self, allowed: bool, safe_reply: str, matched_rules: list[str] | None = None):
        self.allowed = allowed
        self.safe_reply = safe_reply
        self.matched_rules = matched_rules or []


class OutputSafetyFilter:
    _NOTICE = "理财产品不承诺保本或收益，投资需结合您的风险承受能力审慎决策。"

    def inspect(self, reply: str) -> OutputSafetyDecision:
        matched = [rule.name for rule in OUTPUT_RULES if re.search(rule.pattern, reply)]
        if matched:
            return OutputSafetyDecision(False, self._NOTICE, matched)
        return OutputSafetyDecision(True, reply)
