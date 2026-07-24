"""Best-effort incremental Neo4j synchronization for committed MySQL changes."""

from __future__ import annotations

import logging

from app.config.database import get_neo4j_driver
from app.config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def _run(cypher: str, **params: object) -> None:
    driver = get_neo4j_driver()
    async with driver.session(database=settings.neo4j.database) as session:
        result = await session.run(cypher, params)
        await result.consume()


async def sync_holding(customer_id: int, product_id: int, shares: float, current_value: float) -> None:
    """Upsert the customer's active holding relationship."""
    await _run(
        "MERGE (c:Customer {id: $customer_id}) "
        "MERGE (p:Product {id: $product_id}) "
        "MERGE (c)-[r:INVESTS_IN]->(p) "
        "SET r.shares = $shares, r.current_value = $current_value",
        customer_id=customer_id,
        product_id=product_id,
        shares=shares,
        current_value=current_value,
    )


async def remove_holding(customer_id: int, product_id: int) -> None:
    """Remove a holding relationship after the position is fully redeemed."""
    await _run(
        "MATCH (c:Customer {id: $customer_id})-[r:INVESTS_IN]->(p:Product {id: $product_id}) "
        "DELETE r",
        customer_id=customer_id,
        product_id=product_id,
    )


async def sync_risk_level(customer_id: int, risk_level: str) -> None:
    """Replace the customer's graph risk-level relationship atomically in Cypher."""
    graph_level = _to_graph_risk_level(risk_level)
    await _run(
        "MERGE (c:Customer {id: $customer_id}) "
        "OPTIONAL MATCH (c)-[old:HAS_RISK_LEVEL]->(:RiskLevel) "
        "DELETE old "
        "MERGE (level:RiskLevel {level: $risk_level}) "
        "MERGE (c)-[:HAS_RISK_LEVEL]->(level)",
        customer_id=customer_id,
        risk_level=graph_level,
    )


def _to_graph_risk_level(risk_level: str) -> str:
    """将各路径风险等级格式统一映射到 R1-R5（Neo4j 标准格式）

    支持的输入格式:
      - 中文名称: 保守型/稳健型/平衡型/进取型/激进型 → R1/R2/R3/R4/R5
      - C 格式: C1/C2/C3/C4/C5 → R1/R2/R3/R4/R5
      - R 格式: R1/R2/R3/R4/R5 → 直通
    """
    if not risk_level:
        logger.warning("_to_graph_risk_level 收到空值，回退为 R3")
        return "R3"

    # 中文名称映射
    cn_mapping = {
        "保守型": "R1", "稳健型": "R2", "平衡型": "R3",
        "进取型": "R4", "激进型": "R5",
    }
    if risk_level in cn_mapping:
        return cn_mapping[risk_level]

    # C 格式映射 (C1-C5 → R1-R5)
    if risk_level.startswith("C") and len(risk_level) == 2 and risk_level[1:].isdigit():
        level_num = risk_level[1:]
        if level_num in ("1", "2", "3", "4", "5"):
            return f"R{level_num}"

    # R 格式直通 (R1-R5)
    if risk_level.startswith("R") and len(risk_level) == 2 and risk_level[1:].isdigit():
        level_num = risk_level[1:]
        if level_num in ("1", "2", "3", "4", "5"):
            return risk_level

    # 未知格式: 记录告警并尝试数字提取
    import re
    digits = re.findall(r'[1-5]', risk_level)
    if digits:
        fallback = f"R{digits[0]}"
        logger.warning(
            "_to_graph_risk_level 未知格式 '%s'，从文本中提取数字回退为 %s",
            risk_level, fallback,
        )
        return fallback

    logger.error(
        "_to_graph_risk_level 无法识别的格式 '%s'，回退为 R3（需人工核查！）",
        risk_level,
    )
    return "R3"
