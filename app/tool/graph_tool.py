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
        """查询适当性匹配产品（通过 CustomerRiskLevel/ProductRiskLevel 关系）"""
        driver = get_neo4j_driver()
        # 如果传入的是产品风险等级(R1-R5)，转换为对应的客户风险等级(C1-C5)
        crl_level = risk_level if risk_level.startswith("C") else f"C{risk_level[1:]}"
        async with driver.session(database=settings.neo4j.database) as session:
            result = await session.run(
                """
                MATCH (prl:ProductRiskLevel)-[:SUITABLE_FOR]->(crl:CustomerRiskLevel {level_code: $level})
                MATCH (p:Product)-[:HAS_PRODUCT_RISK]->(prl)
                WHERE p.status = '在售'
                RETURN p
                """,
                level=crl_level,
            )
            records = await result.data()
            return [r.get("p", {}) for r in records]

    async def get_collaborative_recommendations(self, customer_id: int) -> List[dict]:
        """
        协同过滤推荐 — 3 跳

        持有相同产品的其他客户，还买了哪些我没买的产品？
        路径: Customer→INVESTS_IN→Product←INVESTS_IN←Peer→INVESTS_IN→NewProduct
        """
        driver = get_neo4j_driver()
        async with driver.session(database=settings.neo4j.database) as session:
            result = await session.run(
                """
                MATCH (c:Customer {id: $cid})-[:INVESTS_IN]->(:Product)<-[:INVESTS_IN]-(peer:Customer)
                      -[:INVESTS_IN]->(rec:Product)
                WHERE NOT (c)-[:INVESTS_IN]->(rec) AND peer.id <> $cid
                WITH rec, count(DISTINCT peer) AS peer_count
                RETURN rec.code AS product_code, rec.name AS product_name, peer_count
                ORDER BY peer_count DESC LIMIT 10
                """,
                cid=customer_id,
            )
            return await result.data()

    async def get_industry_diversify(self, customer_id: int) -> List[dict]:
        """
        行业分散推荐 — 2 跳

        推荐客户持仓中未覆盖的行业的产品
        路径: Customer→INVESTS_IN→Product→BELONGS_TO→Industry (排除已有)
        """
        driver = get_neo4j_driver()
        async with driver.session(database=settings.neo4j.database) as session:
            result = await session.run(
                """
                MATCH (c:Customer {id: $cid})-[:INVESTS_IN]->(:Product)-[:BELONGS_TO]->(i:Industry)
                WITH collect(DISTINCT i.name) AS my_industries
                MATCH (p:Product)-[:BELONGS_TO]->(new_i:Industry)
                WHERE NOT new_i.name IN my_industries
                RETURN p.code AS product_code, p.name AS product_name,
                       new_i.name AS industry, size(my_industries) AS covered_count
                LIMIT 10
                """,
                cid=customer_id,
            )
            return await result.data()

    async def get_peer_purchases(self, customer_id: int) -> List[dict]:
        """
        同风险偏好推荐 — 3 跳

        同一风险等级的其他客户在买什么我没买的？
        路径: Customer→HAS_RISK_LEVEL→RiskLevel←HAS_RISK_LEVEL←Peer→INVESTS_IN→Product
        """
        driver = get_neo4j_driver()
        async with driver.session(database=settings.neo4j.database) as session:
            result = await session.run(
                """
                MATCH (c:Customer {id: $cid})-[:HAS_RISK_LEVEL]->(rl:RiskLevel)
                MATCH (peer:Customer)-[:HAS_RISK_LEVEL]->(rl)
                WHERE peer.id <> $cid
                MATCH (peer)-[:INVESTS_IN]->(p:Product)
                WHERE NOT (c)-[:INVESTS_IN]->(p)
                WITH p, count(DISTINCT peer) AS buyer_count
                RETURN p.code AS product_code, p.name AS product_name, buyer_count
                ORDER BY buyer_count DESC LIMIT 10
                """,
                cid=customer_id,
            )
            return await result.data()
