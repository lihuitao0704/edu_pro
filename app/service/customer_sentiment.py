"""Deterministic customer sentiment signals suitable for profile feedback."""

from __future__ import annotations


_HIGH_DISTRESS = ("亏惨", "睡不着", "崩溃", "活不下去", "绝望", "非常焦虑", "特别焦虑")
_NEGATIVE = ("焦虑", "害怕", "担心", "亏损", "不安", "后悔", "生气", "投诉")


def detect_customer_sentiment(message: str) -> dict:
    text = (message or "").strip()
    high = [word for word in _HIGH_DISTRESS if word in text]
    if high:
        return {"level": "high_distress", "keywords": high}
    negative = [word for word in _NEGATIVE if word in text]
    if negative:
        return {"level": "negative", "keywords": negative}
    return {"level": "neutral", "keywords": []}
