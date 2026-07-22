"""
图谱查询工具（高级封装）
在 app/graph/graph_tool.py 基础上，增加 name 解析、结果格式化
供 operator_agent 和 API 接口直接调用
"""

from typing import List, Optional
from sqlalchemy import text

from app.graph.neo4j_client import Neo4jClient
from app.config.database import async_session_factory


neo4j = Neo4jClient()


async def resolve_customer_id(customer_name: str) -> Optional[int]:
    """根据客户姓名查找 customer_id（MySQL）"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT id FROM sys_user WHERE real_name = :name AND user_type = 'CUSTOMER' LIMIT 1"),
            {"name": customer_name},
        )
        row = result.first()
        return row[0] if row else None


async def resolve_product_id(product_name: str) -> Optional[int]:
    """根据产品名称查找 product_id（MySQL）"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT id FROM fin_product WHERE product_name LIKE :name LIMIT 1"),
            {"name": f"%{product_name}%"},
        )
        row = result.first()
        return row[0] if row else None


async def get_customer_products(customer_name: str) -> List[dict]:
    """
    查询客户持仓产品
    入参: 客户姓名（如"张三"）
    返回: [{product_name, product_code, product_type, shares, current_value, profit_ratio}]
    """
    customer_id = await resolve_customer_id(customer_name)
    if not customer_id:
        return []

    results = await neo4j.run_query(
        """
        MATCH (c:Customer {id: $cid})-[h:INVESTS_IN]->(p:Product)
        RETURN p.name AS product_name, p.code AS product_code,
               p.type AS product_type, p.risk_level AS risk_level,
               h.shares AS shares, h.current_value AS current_value,
               h.profit_ratio AS profit_ratio
        ORDER BY h.current_value DESC
        """,
        {"cid": customer_id},
    )
    # 格式化
    for r in results:
        if r.get("current_value"):
            r["current_value"] = round(float(r["current_value"]), 2)
        if r.get("profit_ratio"):
            r["profit_ratio"] = round(float(r["profit_ratio"]), 2)
        if r.get("shares"):
            r["shares"] = round(float(r["shares"]), 2)
    return results


async def get_suitable_products(risk_level: str, limit: int = 10) -> List[dict]:
    """
    适当性匹配产品查询
    入参: 风险等级（R1-R5），返回不超过该等级的在售产品
    返回: [{product_name, product_code, product_type, risk_level, expected_return}]
    """
    # 映射等级数值
    level_order = {"R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}
    max_level = level_order.get(risk_level, 3)
    suitable_levels = [f"R{i}" for i in range(1, max_level + 1)]

    results = await neo4j.run_query(
        """
        MATCH (p:Product)
        WHERE p.risk_level IN $levels AND p.status = '在售'
        RETURN p.name AS product_name, p.code AS product_code,
               p.type AS product_type, p.risk_level AS risk_level,
               p.expected_return AS expected_return, p.min_amount AS min_amount
        ORDER BY p.expected_return DESC
        LIMIT $limit
        """,
        {"levels": suitable_levels, "limit": limit},
    )
    for r in results:
        if r.get("expected_return"):
            r["expected_return"] = round(float(r["expected_return"]), 2)
        if r.get("min_amount"):
            r["min_amount"] = float(r["min_amount"])
    return results


async def get_product_industry(product_name: str) -> Optional[dict]:
    """
    查询产品所属行业
    入参: 产品名称（支持模糊匹配）
    返回: {product_name, product_code, industry}
    """
    product_id = await resolve_product_id(product_name)
    if not product_id:
        return None

    result = await neo4j.run_single(
        """
        MATCH (p:Product {id: $pid})-[:BELONGS_TO]->(i:Industry)
        RETURN p.name AS product_name, p.code AS product_code, i.name AS industry
        """,
        {"pid": product_id},
    )
    return result


async def get_industry_distribution(customer_name: str) -> List[dict]:
    """
    客户持仓行业分布
    入参: 客户姓名
    返回: [{industry, product_count, total_value}]
    """
    customer_id = await resolve_customer_id(customer_name)
    if not customer_id:
        return []

    results = await neo4j.run_query(
        """
        MATCH (c:Customer {id: $cid})-[h:INVESTS_IN]->(p:Product)-[:BELONGS_TO]->(i:Industry)
        RETURN i.name AS industry, count(p) AS product_count,
               sum(h.current_value) AS total_value
        ORDER BY total_value DESC
        """,
        {"cid": customer_id},
    )
    for r in results:
        if r.get("total_value"):
            r["total_value"] = round(float(r["total_value"]), 2)
    return results
