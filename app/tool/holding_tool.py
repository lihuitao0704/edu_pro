"""Holding Tool — 持仓分析工具"""

from typing import List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class HoldingTool:
    """客户持仓穿透分析工具（供 Agent 调用）"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_holdings(self, customer_id: int) -> List[dict]:
        """获取客户当前持仓"""
        result = await self.db.execute(
            text(
                """
                SELECT h.product_id, h.current_value, h.profit_loss, h.profit_ratio
                FROM fin_holdings h
                WHERE h.customer_id = :cid AND h.status = '持仓中'
                """
            ),
            {"cid": customer_id},
        )
        rows = result.fetchall()
        return [
            {
                "product_id": r[0],
                "current_value": float(r[1]) if r[1] else 0,
                "profit_loss": float(r[2]) if r[2] else 0,
                "profit_ratio": float(r[3]) if r[3] else 0,
            }
            for r in rows
        ]

    async def get_concentration_risk(self, customer_id: int) -> dict:
        """分析持仓集中度"""
        holdings = await self.get_holdings(customer_id)
        total = sum(h["current_value"] for h in holdings)

        if total == 0:
            return {"total_value": 0, "concentration": "无持仓", "product_count": 0}

        max_single = max(h["current_value"] for h in holdings) if holdings else 0
        concentration = max_single / total if total > 0 else 0

        return {
            "total_value": round(total, 2),
            "product_count": len(holdings),
            "max_single_ratio": round(concentration, 2),
            "warning": "单产品持仓过于集中" if concentration > 0.5 else None,
        }
