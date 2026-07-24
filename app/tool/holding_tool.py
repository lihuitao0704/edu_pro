"""Holding Tool — 持仓分析工具（SQL + Neo4j 双数据源）"""

from typing import List, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_neo4j_driver
from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class HoldingTool:
    """客户持仓穿透分析工具（供 Agent 调用）

    数据来源：
      - MySQL (fin_holdings)：持仓明细、盈亏数据
      - Neo4j (图谱)：行业归属、产品关联关系
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ═══════════════════════════════════════════════════════════════
    # MySQL 数据查询
    # ═══════════════════════════════════════════════════════════════

    async def get_holdings(self, customer_id: int) -> List[dict]:
        """获取客户当前持仓"""
        result = await self.db.execute(
            text(
                """
                SELECT h.product_id, h.current_value, h.profit_loss, h.profit_ratio
                FROM fin_holdings h
                WHERE h.customer_id = :cid AND h.status = '持有中'
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

    async def get_profit_loss_summary(self, customer_id: int) -> dict:
        """盈亏汇总"""
        holdings = await self.get_holdings(customer_id)
        total_value = sum(h["current_value"] for h in holdings)
        total_pl = sum(h["profit_loss"] for h in holdings)

        profit_count = sum(1 for h in holdings if h["profit_loss"] > 0)
        loss_count = sum(1 for h in holdings if h["profit_loss"] < 0)
        flat_count = sum(1 for h in holdings if h["profit_loss"] == 0)

        avg_ratio = (
            sum(h["profit_ratio"] for h in holdings) / len(holdings)
            if holdings else 0
        )

        return {
            "total_value": round(total_value, 2),
            "total_profit_loss": round(total_pl, 2),
            "avg_profit_ratio": round(avg_ratio, 4),
            "profit_count": profit_count,
            "loss_count": loss_count,
            "flat_count": flat_count,
        }

    # ═══════════════════════════════════════════════════════════════
    # Neo4j 图谱查询
    # ═══════════════════════════════════════════════════════════════

    async def get_industry_distribution(self, customer_id: int) -> List[dict]:
        """通过 Neo4j 查询客户持仓的行业分布"""
        try:
            driver = get_neo4j_driver()
            async with driver.session(database=settings.neo4j.database) as session:
                result = await session.run(
                    """
                    MATCH (c:Customer {id: $id})-[:INVESTS_IN]->(p:Product)-[:BELONGS_TO]->(i:Industry)
                    RETURN i.name AS industry, count(p) AS product_count, collect(p.name) AS products
                    ORDER BY product_count DESC
                    """,
                    id=customer_id,
                )
                return await result.data()
        except Exception as e:
            logger.warning(f"Neo4j 行业分布查询失败: {e}")
            return []

    async def get_product_industry(self, product_id: str) -> Optional[str]:
        """查询单个产品所属行业"""
        try:
            driver = get_neo4j_driver()
            async with driver.session(database=settings.neo4j.database) as session:
                result = await session.run(
                    "MATCH (p:Product {code: $code})-[:BELONGS_TO]->(i:Industry) RETURN i.name AS industry",
                    code=product_id,
                )
                record = await result.single()
                return record["industry"] if record else None
        except Exception as e:
            logger.warning(f"Neo4j 产品行业查询失败: {e}")
            return None

    # ═══════════════════════════════════════════════════════════════
    # 综合分析（Agent 主入口）
    # ═══════════════════════════════════════════════════════════════

    async def analyze(self, customer_id: int) -> dict:
        """
        综合分析客户持仓：持仓明细 + 行业分布 + 集中度 + 盈亏状态

        供 Agent 直接调用，返回 LLM 友好的结构化结果。
        """
        # 并行获取 MySQL 和 Neo4j 数据
        holdings = await self.get_holdings(customer_id)
        concentration = await self.get_concentration_risk(customer_id)
        pl_summary = await self.get_profit_loss_summary(customer_id)
        industry_dist = await self.get_industry_distribution(customer_id)

        # 计算行业集中度
        industry_count = len(industry_dist)
        industry_warning = None
        if industry_count == 1:
            industry_warning = "⚠️ 持仓集中在单一行业，缺乏行业分散度，建议跨行业配置"
        elif industry_count == 2:
            industry_warning = "⚠️ 持仓仅分布在2个行业，行业集中度偏高"

        # 盈亏状态评估
        total_pl = pl_summary["total_profit_loss"]
        if total_pl < 0:
            pl_assessment = "整体持仓处于亏损状态，需关注持仓结构"
        elif total_pl == 0:
            pl_assessment = "持仓整体持平"
        else:
            pl_assessment = "整体持仓处于盈利状态"

        return {
            "customer_id": customer_id,
            "holdings_count": len(holdings),
            "holdings": holdings,
            "concentration": concentration,
            "profit_loss_summary": pl_summary,
            "pl_assessment": pl_assessment,
            "industry_distribution": {
                "industry_count": len(industry_dist),
                "industries": [
                    {
                        "name": d.get("industry", "未知"),
                        "product_count": d.get("product_count", 0),
                        "products": d.get("products", []),
                    }
                    for d in industry_dist
                ],
                "warning": industry_warning,
            },
        }
