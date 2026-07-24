"""Neo4j 图数据库客户端"""

import logging
from typing import List, Optional
from app.config.database import get_neo4j_driver
from app.config.settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# 合法节点标签白名单，防止 Cypher 注入
VALID_LABELS = frozenset({
    "Customer", "Product", "CustomerRiskLevel", "ProductRiskLevel",
    "Industry", "FundManager", "Market", "Transaction", "Employee",
    "Knowledge"
})

# 单次查询最大返回条数（防止 OOM）
MAX_RESULT_ROWS = 1000


class Neo4jQueryError(Exception):
    """Neo4j 查询异常（Cypher 语法/语义错误）"""


class Neo4jConnectionError(Exception):
    """Neo4j 连接异常（服务不可用/超时）"""


class Neo4jClient:
    """Neo4j 操作封装"""

    async def run_query(self, cypher: str, params: dict = None,
                        timeout: int = None, limit: Optional[int] = None) -> List[dict]:
        """
        执行 Cypher 查询

        Args:
            cypher: Cypher 查询语句
            params: 查询参数
            timeout: 查询超时（秒），默认使用 settings.neo4j.timeout
            limit: 结果最大条数。None=使用默认上限；传 0 或负数表示不限制
        """
        driver = get_neo4j_driver()
        timeout = timeout or settings.neo4j.timeout
        # limit=None 表示使用默认上限；limit<=0 表示不限制
        effective_limit = MAX_RESULT_ROWS if limit is None else limit
        no_limit = effective_limit <= 0

        # 自动追加 LIMIT（仅在语句未包含 LIMIT/RETURN count 时）
        if not no_limit:
            cypher_upper = cypher.upper().rstrip()
            if "LIMIT" not in cypher_upper and "COUNT(" not in cypher_upper:
                cypher = cypher.rstrip() + f"\nLIMIT {int(effective_limit)}"

        try:
            async with driver.session(database=settings.neo4j.database) as session:
                result = await session.run(cypher, params or {})
                # 限制结果条数（兜底，防止 Cypher 本身绕过 LIMIT）
                records = []
                async for record in result:
                    records.append(dict(record))
                    if not no_limit and len(records) >= effective_limit:
                        break
                return records
        except Exception as e:
            err_name = type(e).__name__
            logger.error(f"[Neo4j] 查询失败 ({err_name}): {e} | cypher={cypher[:200]}")
            # 区分连接异常和查询异常
            if "ServiceUnavailable" in err_name or "SessionExpired" in err_name \
                    or "Connection" in err_name or "Timeout" in err_name:
                raise Neo4jConnectionError(f"图谱服务暂时不可用: {err_name}") from e
            raise Neo4jQueryError(f"Cypher 查询失败: {e}") from e

    async def run_single(self, cypher: str, params: dict = None,
                         timeout: int = None) -> Optional[dict]:
        """执行查询并返回单条结果"""
        data = await self.run_query(cypher, params, timeout=timeout, limit=1)
        return data[0] if data else None

    async def get_node_count(self, label: str) -> int:
        """获取节点数量（label 需通过白名单校验）"""
        if label not in VALID_LABELS:
            raise ValueError(f"非法节点标签: {label}，允许值: {VALID_LABELS}")
        data = await self.run_query(f"MATCH (n:{label}) RETURN count(n) AS cnt", limit=0)
        return data[0]["cnt"] if data else 0

    async def get_stats(self) -> dict:
        """获取图谱统计信息（单次查询获取所有节点和关系计数）"""
        union_parts = " UNION ".join(
            f"MATCH (n:{label}) RETURN '{label}' AS label, count(n) AS cnt"
            for label in sorted(VALID_LABELS)
        )
        union_parts += " UNION MATCH ()-[r]->() RETURN '__relationships__' AS label, count(r) AS cnt"

        # 统计查询不需要条数限制
        data = await self.run_query(union_parts, limit=0)

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
