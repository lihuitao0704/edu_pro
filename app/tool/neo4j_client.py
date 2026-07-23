"""Neo4j 图数据库客户端"""

from typing import List, Optional
from app.config.database import get_neo4j_driver
from app.config.settings import get_settings

settings = get_settings()

# 合法节点标签白名单，防止 Cypher 注入
VALID_LABELS = frozenset({"Customer", "Product", "RiskLevel", "Industry", "FundManager", "Market"})


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
        """获取节点数量（label 需通过白名单校验）"""
        if label not in VALID_LABELS:
            raise ValueError(f"非法节点标签: {label}，允许值: {VALID_LABELS}")
        data = await self.run_query(f"MATCH (n:{label}) RETURN count(n) AS cnt")
        return data[0]["cnt"] if data else 0

    async def get_stats(self) -> dict:
        """获取图谱统计信息（单次查询获取所有节点和关系计数）"""
        union_parts = " UNION ".join(
            f"MATCH (n:{label}) RETURN '{label}' AS label, count(n) AS cnt"
            for label in sorted(VALID_LABELS)
        )
        union_parts += " UNION MATCH ()-[r]->() RETURN '__relationships__' AS label, count(r) AS cnt"

        data = await self.run_query(union_parts)

        node_counts = {}
        rel_count = 0
        for row in data:
            if row["label"] == "__relationships__":
                rel_count = row["cnt"]
            else:
                node_counts[row["label"]] = row["cnt"]

        # 确保所有标签都存在（即使计数为0）
        for label in VALID_LABELS:
            node_counts.setdefault(label, 0)

        return {"nodes": node_counts, "relationships": rel_count}
