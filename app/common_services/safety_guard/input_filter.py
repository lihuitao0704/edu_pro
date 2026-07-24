import re

from app.common_services.context_manager.models import SafetyDecision
from app.common_services.safety_guard.risk_rule import INPUT_RULES


class InputSafetyFilter:
    _PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
    _ID_CARD = re.compile(r"(?<![\dXx])(\d{17}[\dXx])(?![\dXx])")
    _BANK_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)")

    def inspect(self, text: str) -> SafetyDecision:
        for rule in INPUT_RULES:
            if re.search(rule.pattern, text, flags=re.IGNORECASE):
                return SafetyDecision(
                    blocked=True,
                    sanitized_text="",
                    user_message="为了保护您的隐私，请不要在聊天中输入密码、验证码、银行卡号等敏感信息。",
                    matched_rules=[rule.name],
                )
        if self._ID_CARD.search(text) or self._BANK_CARD.search(text):
            return SafetyDecision(
                blocked=True,
                sanitized_text="",
                user_message="为了保护您的隐私，请不要在聊天中输入身份证号码或银行卡号等敏感信息。",
                matched_rules=["identity_or_bank_card"],
            )
        masked = self._PHONE.sub(lambda m: f"{m.group(1)[:3]}****{m.group(1)[-4:]}", text)
        masked = self._ID_CARD.sub(lambda m: f"{m.group(1)[:6]}********{m.group(1)[-4:]}", masked)
        masked = self._BANK_CARD.sub(lambda m: self._mask_bank(m.group(0)), masked)
        return SafetyDecision(sanitized_text=masked)

    @staticmethod
    def _mask_bank(value: str) -> str:
        digits = re.sub(r"\D", "", value)
        return f"{digits[:4]}****{digits[-4:]}"
