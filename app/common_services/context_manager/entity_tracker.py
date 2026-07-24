import re
from typing import Any


class EntityTracker:
    """Deterministic entity extraction with explicit session reference resolution."""

    _REFERENCE_WORDS = ("它", "该产品", "这个产品", "刚才那个")
    _PRODUCT_AFTER_QUERY = re.compile(
        r"(?:查(?:一下|询)?|产品(?:是|为)?|基金(?:是|为)?|关于)\s*"
        r"([\u4e00-\u9fffA-Za-z0-9]{2,30}(?:混合|基金|理财|债券|货币)[A-Za-z0-9]*)"
    )

    def track(self, message: str, previous_entities: dict[str, Any] | None = None) -> dict[str, Any]:
        previous_entities = previous_entities or {}
        match = self._PRODUCT_AFTER_QUERY.search(message)
        if match:
            return {"product_name": match.group(1), "product_source": "message"}
        if any(word in message for word in self._REFERENCE_WORDS):
            product_name = previous_entities.get("product_name")
            if product_name:
                return {"product_name": product_name, "product_source": "session"}
        return {}
