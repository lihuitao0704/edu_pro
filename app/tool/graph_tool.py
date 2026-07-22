"""Graph Tool — 图谱查询工具"""

from typing import List, Optional
from app.config.database import get_neo4j_driver
from app.config.settings import get_settings

settings = get_settings()


class GraphTool:
    """Neo4j 图谱查询工具（供 Agent 调用）"""

    async def get_customer_products(self, customer_id: int) -> List[dict]:
        """查询客户持仓产品"""
        driver = get_neo4j_driver()
        async with driver.session(database=settings.neo4j.database) as session:
            result = await session.run(
                "MATCH (c:Customer {id: $id})-[:INVESTS_IN]->(p:Product) RETURN p LIMIT 20",
                id=customer_id,
            )
            records = await result.data()
            return [r.get("p", {}) for r in records]

    async def get_product_industry(self, product_code: str) -> Optional[str]:
        """查询产品所属行业"""
        driver = get_neo4j_driver()
        async with driver.session(database=settings.neo4j.database) as session:
            result = await session.run(
                "MATCH (p:Product {code: $code})-[:BELONGS_TO]->(i:Industry) RETURN i.name",
                code=product_code,
            )
            record = await result.single()
            return record["i.name"] if record else None

    async def get_industry_distribution(self, customer_id: int) -> List[dict]:
        """客户持仓行业分布"""
        driver = get_neo4j_driver()
        async with driver.session(database=settings.neo4j.database) as session:
            result = await session.run(
                """
                MATCH (c:Customer {id: $id})-[:INVESTS_IN]->(p:Product)-[:BELONGS_TO]->(i:Industry)
                RETURN i.name AS industry, count(p) AS count
                """,
                id=customer_id,
            )
            return await result.data()

    async def get_suitable_products(self, risk_level: str) -> List[dict]:
        """查询适当性匹配产品"""
        driver = get_neo4j_driver()
        async with driver.session(database=settings.neo4j.database) as session:
            result = await session.run(
                "MATCH (r:RiskLevel {level: $level})-[:HAS_PRODUCT]->(p:Product) RETURN p",
                level=risk_level,
            )
            records = await result.data()
            return [r.get("p", {}) for r in records]
