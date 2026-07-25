"""Safe user-facing narration for structured advisor recommendations."""


class AdvisorNarrativeService:
    RISK_DISCLAIMER = "投资有风险，入市需谨慎。以上内容不构成投资建议。"

    @classmethod
    def ensure_disclaimer(cls, text: str) -> str:
        cleaned = (text or "").strip()
        if cls.RISK_DISCLAIMER in cleaned:
            return cleaned
        return f"{cleaned}\n\n{cls.RISK_DISCLAIMER}".strip()

    @classmethod
    def render_template(cls, result: dict) -> str:
        profile = result.get("customer_profile") or {}
        assessment = profile.get("assessment") if isinstance(profile, dict) else {}
        risk_level = (assessment or {}).get("risk_level", "当前")
        names = [item.get("product_name", "产品") for item in result.get("recommendations", [])]
        product_text = "、".join(names[:3]) or "暂未找到可展示的产品"
        return cls.ensure_disclaimer(f"已基于客户 {risk_level} 风险画像完成匹配：{product_text}。")
