"""
Entity Tracker — 会话级实体识别与指代消解。

从用户自然语言消息中提取实体（产品、客户、风险等级、金额等），
并解析代词指代（"它""这个""刚才的"）关联到会话上下文。
"""

import re
from typing import Any


class EntityTracker:
    """Deterministic multi-type entity extraction with session reference resolution.

    支持的实体类型:
      - product: 产品名称（含模糊指代消解）
      - customer: 客户名称/ID
      - risk_level: 风险等级 (R1-R5/C1-C5/中文)
      - amount: 金额
      - date: 日期
    """

    # 指代词 → 解析策略
    _REFERENCE_PATTERNS = {
        "product": (
            "它", "该产品", "这个产品", "刚才那个", "这个基金",
            "这只", "那只", "这个", "那个",
        ),
        "customer": ("这个人", "这个客户", "该客户", "他", "她", "这位"),
    }

    # 产品名称匹配（含常见理财产品后缀）
    _PRODUCT_PATTERN = re.compile(
        r"(?:查(?:一下|询)?|产品(?:是|为)?|基金(?:是|为)?|关于|推荐|买)\s*"
        r"([一-鿿A-Za-z0-9]{2,30}(?:混合|基金|理财|债券|货币|ETF|指数|增强|联接)[A-Za-z0-9]*)"
    )

    # 产品代码匹配 (Fxxxxxx 格式)
    _PRODUCT_CODE_PATTERN = re.compile(r"\b(F\d{5,7})\b")

    # 客户名称匹配
    _CUSTOMER_PATTERN = re.compile(
        r"(?:客户|用户|给)\s*([一-鿿]{2,4})(?:推荐|查询|分析|看一下|评估)"
    )

    # 风险等级匹配
    _RISK_LEVEL_PATTERN = re.compile(
        r"\b([RrCc][1-5])\b|(保守型|稳健型|平衡型|进取型|激进型)"
    )

    # 金额匹配
    _AMOUNT_PATTERN = re.compile(
        r"(\d+(?:\.\d+)?)\s*(?:万元|万|元|块)"
    )

    def track(
        self,
        message: str,
        previous_entities: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """从消息中提取实体，解析指代。

        Args:
            message: 用户当前消息
            previous_entities: 上次提取的实体（用于指代消解）

        Returns:
            提取到的实体 dict，key 为实体类型名
        """
        previous_entities = previous_entities or {}
        result: dict[str, Any] = {}

        # 1. 产品名称提取
        product = self._extract_product(message, previous_entities)
        if product:
            result["product_name"] = product["name"]
            result["product_source"] = product["source"]

        # 2. 产品代码提取
        code_match = self._PRODUCT_CODE_PATTERN.search(message)
        if code_match:
            result["product_code"] = code_match.group(1)
            result["product_code_source"] = "message"

        # 3. 客户名称提取
        customer = self._extract_customer(message, previous_entities)
        if customer:
            result["customer_name"] = customer["name"]
            result["customer_source"] = customer["source"]

        # 4. 风险等级提取
        risk_match = self._RISK_LEVEL_PATTERN.search(message)
        if risk_match:
            level = risk_match.group(1) or risk_match.group(2)
            if level:
                result["risk_level"] = level
                result["risk_level_source"] = "message"

        # 5. 金额提取
        amount_match = self._AMOUNT_PATTERN.search(message)
        if amount_match:
            result["amount_value"] = float(amount_match.group(1))
            result["amount_unit"] = amount_match.group(2)

        return result

    def _extract_product(
        self, message: str, previous: dict[str, Any]
    ) -> dict[str, str] | None:
        """Extract product name or resolve pronoun reference."""
        # 先尝试直接匹配
        match = self._PRODUCT_PATTERN.search(message)
        if match:
            return {"name": match.group(1), "source": "message"}

        # 尝试指代消解
        ref_words = self._REFERENCE_PATTERNS["product"]
        if any(word in message for word in ref_words):
            product_name = previous.get("product_name")
            if product_name:
                return {"name": product_name, "source": "session_reference"}

        return None

    def _extract_customer(
        self, message: str, previous: dict[str, Any]
    ) -> dict[str, str] | None:
        """Extract customer name or resolve pronoun reference."""
        match = self._CUSTOMER_PATTERN.search(message)
        if match:
            return {"name": match.group(1), "source": "message"}

        ref_words = self._REFERENCE_PATTERNS["customer"]
        if any(word in message for word in ref_words):
            customer_name = previous.get("customer_name")
            if customer_name:
                return {"name": customer_name, "source": "session_reference"}

        return None
