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
    mapping = {"保守型": "R1", "稳健型": "R2", "平衡型": "R3", "进取型": "R4", "激进型": "R5"}
    if risk_level in mapping:
        return mapping[risk_level]
    if risk_level.startswith("C") and risk_level[1:].isdigit():
        return f"R{risk_level[1:]}"
    return risk_level
