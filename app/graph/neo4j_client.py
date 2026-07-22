"""Neo4j 图数据库客户端"""

from typing import List, Optional
from app.config.database import get_neo4j_driver
from app.config.settings import get_settings

settings = get_settings()


class Neo4jClient:
    """Neo4j 操作封装"""

    async def run_query(self, cypher: str, params: dict = None) -> List[dict]:
        """执行 Cypher 查询"""
        driver = get_neo4j_driver()
        async with driver.session(database=settings.neo4j.database) as session:
            result = await session.run(cypher, params or {})
            return await result.data()

    async def run_single(self, cypher: str, params: dict = None) -> Optional[dict]:
        """执行查询并返回单条结果"""
        data = await self.run_query(cypher, params)
        return data[0] if data else None

    async def get_node_count(self, label: str) -> int:
        """获取节点数量"""
        data = await self.run_query(f"MATCH (n:{label}) RETURN count(n) AS cnt")
        return data[0]["cnt"] if data else 0

    async def get_stats(self) -> dict:
        """获取图谱统计信息"""
        node_counts = {}
        for label in ["Customer", "Product", "RiskLevel", "Industry", "FundManager"]:
            node_counts[label] = await self.get_node_count(label)

        rel_data = await self.run_query("MATCH ()-[r]->() RETURN count(r) AS cnt")
        rel_count = rel_data[0]["cnt"] if rel_data else 0

        return {"nodes": node_counts, "relationships": rel_count}
