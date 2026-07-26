"""Deterministic investment-budget allocation with product constraint checks."""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN


_TYPE_TO_CATEGORY = {
    "货币型": "货币类",
    "债券型": "债券类",
    "混合型": "混合类",
    "股票型": "股票类",
}


class BudgetAllocationService:
    """Turn percentage targets into executable amounts without using an LLM."""

    @staticmethod
    def _money(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    @classmethod
    def build(
        cls,
        investment_amount: float | int,
        recommendations: list[dict],
        allocation: dict | None,
    ) -> dict:
        total = cls._money(Decimal(str(investment_amount)))
        if total <= 0:
            return {"status": "invalid_amount", "investment_amount": float(total)}

        allocation_map = (
            allocation.get("allocation", {})
            if isinstance(allocation, dict)
            else {}
        )
        if not isinstance(allocation_map, dict) or not allocation_map:
            allocation_map = {"债券类": 60.0, "货币类": 30.0, "现金": 10.0}

        products_by_category: dict[str, list[dict]] = {}
        for product in recommendations or []:
            category = _TYPE_TO_CATEGORY.get(str(product.get("product_type") or ""))
            if not category:
                continue
            minimum = cls._money(Decimal(str(product.get("min_amount") or 0)))
            if minimum > total:
                continue
            products_by_category.setdefault(category, []).append(
                {**product, "_minimum": minimum}
            )

        product_allocations: list[dict] = []
        unallocated = Decimal("0")
        allocated_total = Decimal("0")

        for category, raw_percentage in allocation_map.items():
            try:
                percentage = Decimal(str(raw_percentage))
            except Exception:
                continue
            category_budget = cls._money(total * percentage / Decimal("100"))
            if category == "现金":
                unallocated += category_budget
                continue
            candidates = products_by_category.get(category, [])
            if not candidates:
                unallocated += category_budget
                continue

            selected = list(candidates)
            while selected:
                per_product = cls._money(category_budget / Decimal(len(selected)))
                infeasible = [
                    product
                    for product in selected
                    if per_product < product["_minimum"]
                ]
                if not infeasible:
                    break
                selected.remove(max(infeasible, key=lambda item: item["_minimum"]))

            if not selected:
                unallocated += category_budget
                continue

            remaining = category_budget
            for index, product in enumerate(selected):
                amount = (
                    remaining
                    if index == len(selected) - 1
                    else cls._money(category_budget / Decimal(len(selected)))
                )
                remaining -= amount
                if amount < product["_minimum"]:
                    unallocated += amount
                    continue
                allocated_total += amount
                product_allocations.append(
                    {
                        "product_code": product.get("product_code"),
                        "product_name": product.get("product_name"),
                        "product_type": product.get("product_type"),
                        "risk_level": product.get("risk_level"),
                        "amount": float(amount),
                        "min_amount": float(product["_minimum"]),
                        "constraint_valid": True,
                    }
                )

        accounted = allocated_total + unallocated
        if accounted < total:
            unallocated += total - accounted

        return {
            "status": "ready",
            "investment_amount": float(total),
            "product_allocations": product_allocations,
            "cash_reserve": float(cls._money(unallocated)),
            "allocated_amount": float(cls._money(allocated_total)),
            "constraint_valid": all(
                Decimal(str(item["amount"])) >= Decimal(str(item["min_amount"]))
                for item in product_allocations
            )
            and cls._money(allocated_total + unallocated) == total,
        }
