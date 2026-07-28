import re

from app.common_services.context_manager.models import SafetyDecision
from app.common_services.safety_guard.risk_rule import INPUT_RULES


class InputSafetyFilter:
    _PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
    _ID_CARD = re.compile(r"(?<![\dXx])(\d{17}[\dXx])(?![\dXx])")
    _BANK_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)")

    # 辱骂/不当语言检测
    _ABUSIVE = re.compile(
        r"(操你|fuck|shit|damn|傻逼|脑残|sb|cnm|tmd|nmsl|妈的|逼|婊子|贱人|畜生|去死|滚"
        r"|神经病|脑子有泡|脑子有病|脑子进水|智障|弱智|白痴|废物|蠢货|笨蛋|猪头"
        r"|有病|疯子|神经|傻缺|二逼|二货|憨批|瓜皮|辣鸡|垃圾|去你妈|你大爷"
        r"|狗日的|王八蛋|混蛋|杂种|贱货|骚货|婊|屌|日你|草泥马|卧槽|我操"
        r"|杀了你|杀死|砍死|揍你|打你|弄死|干掉|宰了你|灭了你|弄死你"
        r"|杀你全家|杀.*全家|灭.*全家|屠.*全家|炸.*全家|烧.*全家"
        r"|杀你|杀光|宰了你|活埋|分尸|碎尸|剥皮|凌迟|爆头|枪毙|毒死|勒死|淹死|烧死|炸死"
        r"|弄死全家|灭门|满门抄斩|死全家|全家死|全家.*死|诅咒.*死|诅咒.*杀)",
        re.IGNORECASE
    )

    # 违规金融承诺检测（用户输入中包含此类内容时直接拦截）
    _FINANCIAL_VIOLATION = re.compile(
        r"(100%.*收益|零风险.*理财|稳赚不赔|保证.*收益|保本.*高收益"
        r"|内幕消息|代客操作|代客理财|非法集资|庞氏骗局|传销"
        r"|刚性兑付|老鼠仓|利益输送)",
        re.IGNORECASE
    )

    def inspect(self, text: str) -> SafetyDecision:
        # 检查辱骂内容
        if self._ABUSIVE.search(text):
            return SafetyDecision(
                blocked=True,
                sanitized_text="",
                user_message="您的输入包含不当内容，请使用文明用语。如有业务问题，请重新描述。",
                matched_rules=["abusive_language"],
            )

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
