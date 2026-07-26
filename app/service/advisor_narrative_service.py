"""Safe user-facing narration for structured advisor recommendations."""


class AdvisorNarrativeService:
    RISK_DISCLAIMER = "投资有风险，入市需谨慎。以上内容不构成投资建议。"
    _LEAK_MARKERS = (
        "我们被要求",
        "系统要求",
        "提示词",
        "prompt",
        "作为ai",
        "作为 AI",
        "需要生成",
        "我要把",
        "字以内",
    )

    @classmethod
    def ensure_disclaimer(cls, text: str) -> str:
        cleaned = (text or "").strip()
        if "投资有风险" in cleaned and "不构成投资建议" in cleaned:
            return cleaned
        return f"{cleaned}\n\n{cls.RISK_DISCLAIMER}".strip()

    @classmethod
    def safe_reason(cls, reason: str, product: dict) -> str:
        cleaned = " ".join(str(reason or "").split())
        if (
            not cleaned
            or len(cleaned) > 100
            or any(marker.lower() in cleaned.lower() for marker in cls._LEAK_MARKERS)
        ):
            product_type = product.get("product_type") or "产品"
            risk_level = product.get("risk_level") or "相应"
            return f"该{product_type}为{risk_level}风险等级，可作为分散配置参考。"
        return cleaned

    @classmethod
    def render_customer(cls, result: dict) -> str:
        """Render only customer-appropriate facts from structured recommendation data."""
        profile = result.get("customer_profile") or {}
        assessment = profile.get("assessment") if isinstance(profile, dict) else {}
        risk_level = (
            (assessment or {}).get("risk_level")
            or (profile.get("risk_level") if isinstance(profile, dict) else None)
            or "当前"
        )
        alerts = result.get("risk_alerts") or {}
        alert_level = str(alerts.get("alert_level") or "").lower()
        recommendations = list(result.get("recommendations") or [])[:3]

        lines = [f"已结合您当前的 **{risk_level}** 风险承受能力完成产品筛选。"]
        if alert_level in {"high", "medium"}:
            lines.append(
                "\n> 您的账户有一项风险事项待确认，本次仅展示 R1-R2 产品。"
                "如需了解或处理该事项，可联系理财顾问。"
            )

        if recommendations:
            lines.append("\n### 适合您的产品")
            for index, product in enumerate(recommendations, start=1):
                name = product.get("product_name") or "产品"
                risk = product.get("risk_level") or "未标注"
                product_type = product.get("product_type") or "未标注类型"
                expected_return = product.get("expected_return")
                return_text = (
                    f"，参考年化 {float(expected_return):.2f}%"
                    if expected_return is not None
                    else ""
                )
                reason = cls.safe_reason(product.get("reason", ""), product)
                lines.append(
                    f"{index}. **{name}**（{risk} · {product_type}{return_text}）\n"
                    f"   {reason}"
                )
        else:
            lines.append(
                "\n暂未找到同时满足适当性规则和数据质量要求的在售产品。"
                "您可以稍后重试，或联系理财顾问进一步了解。"
            )

        return cls.ensure_disclaimer("\n".join(lines))

    @classmethod
    def render_template(cls, result: dict) -> str:
        profile = result.get("customer_profile") or {}
        assessment = profile.get("assessment") if isinstance(profile, dict) else {}
        risk_level = (assessment or {}).get("risk_level", "当前")
        names = [item.get("product_name", "产品") for item in result.get("recommendations", [])]
        product_text = "、".join(names[:3]) or "暂未找到可展示的产品"
        return cls.ensure_disclaimer(f"已基于客户 {risk_level} 风险画像完成匹配：{product_text}。")
