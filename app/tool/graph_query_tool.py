"""
图谱查询工具（高级封装）
在 app/graph/graph_tool.py 基础上，增加 name 解析、结果格式化
供 operator_agent 和 API 接口直接调用
"""

from typing import List, Optional
from sqlalchemy import text

from app.tool.neo4j_client import Neo4jClient
from app.config.database import async_session_factory


neo4j = Neo4jClient()


import re


async def resolve_customer_id(customer_name: str) -> Optional[int]:
    """根据客户姓名或ID描述查找 customer_id（MySQL）

    解析策略（按优先级）：
    1. 精确匹配 real_name（保持向后兼容）
    2. "客户ID N" / "客户ID：N" / "客户编号N" 模式 → 直接按ID查询
    3. 名字含数字后缀（如"演示客户05"）→ 提取数字作为候选ID查询
    4. 模糊匹配（最后兜底）
    """
    if not customer_name or not customer_name.strip():
        return None
    name = customer_name.strip()

    async with async_session_factory() as session:
        # 策略1: 精确匹配 real_name
        result = await session.execute(
            text("SELECT id FROM sys_user WHERE real_name = :name AND user_type = 'CUSTOMER'"),
            {"name": name},
        )
        rows = result.fetchall()
        if len(rows) == 1:
            cid = rows[0][0]
            print(f"[resolve_customer_id] 策略1命中 | name={name} | id={cid}")
            return cid
        if len(rows) > 1:
            # 存在重名：拒绝猜测
            print(f"[resolve_customer_id] 策略1失败: 重名 | name={name} | count={len(rows)}")
            return None

        # 策略2: "客户ID N" / "客户编号N" 模式
        id_patterns = [
            r'客户\s*ID\s*[：:]\s*(\d+)',
            r'客户\s*ID\s*(\d+)',
            r'客户编号\s*[：:]*\s*(\d+)',
            r'customer\s*id\s*[：:=]*\s*(\d+)',
        ]
        for pattern in id_patterns:
            m = re.search(pattern, name, re.IGNORECASE)
            if m:
                cid = int(m.group(1))
                # 验证该ID确实存在且是客户
                verify = await session.execute(
                    text("SELECT id FROM sys_user WHERE id = :cid AND user_type = 'CUSTOMER'"),
                    {"cid": cid},
                )
                if verify.first():
                    print(f"[resolve_customer_id] 策略2命中 | name={name} | id={cid}")
                    return cid
                else:
                    print(f"[resolve_customer_id] 策略2失败: ID {cid} 不是客户")

        # 策略3: 名字含数字后缀（如"演示客户05" → 05 → 5）
        # 提取名字末尾的数字（支持零填充）
        num_match = re.search(r'(\d+)$', name)
        if num_match:
            num_str = num_match.group(1)
            candidate_id = int(num_str)  # "05" → 5, "15" → 15
            # 验证该ID存在且是客户
            verify = await session.execute(
                text("SELECT id FROM sys_user WHERE id = :cid AND user_type = 'CUSTOMER'"),
                {"cid": candidate_id},
            )
            if verify.first():
                print(f"[resolve_customer_id] 策略3命中 | name={name} | id={candidate_id}")
                return candidate_id
            else:
                print(f"[resolve_customer_id] 策略3失败: ID {candidate_id} 不是客户")

        # 策略4: 模糊 LIKE 匹配（最后兜底）
        result = await session.execute(
            text("SELECT id FROM sys_user WHERE real_name LIKE :pat AND user_type = 'CUSTOMER' LIMIT 2"),
            {"pat": f"%{name}%"},
        )
        rows = result.fetchall()
        if len(rows) == 1:
            cid = rows[0][0]
            print(f"[resolve_customer_id] 策略4命中 | name={name} | id={cid}")
            return cid

        print(f"[resolve_customer_id] 所有策略失败 | name={name}")
        return None


async def resolve_product_id(product_name: str) -> Optional[int]:
    """根据产品名称查找 product_id（MySQL）
    优先精确匹配，无结果时 fallback 到模糊匹配"""
    async with async_session_factory() as session:
        # 精确匹配
        result = await session.execute(
            text("SELECT id FROM fin_product WHERE product_name = :name LIMIT 1"),
            {"name": product_name},
        )
        row = result.first()
        if row:
            return row[0]
        # 模糊匹配
        result = await session.execute(
            text("SELECT id FROM fin_product WHERE product_name LIKE :name LIMIT 1"),
            {"name": f"%{product_name}%"},
        )
        row = result.first()
        return row[0] if row else None


async def get_customer_products(customer_name: str):
    """
    查询客户持仓产品
    入参: 客户姓名（如"张三"）
    返回: (found: bool, data: list|str)
      - (True, [...]) 找到客户且有持仓
      - (True, [])   找到客户但无持仓
      - (False, msg) 未找到客户（精确匹配失败或重名）
    """
    customer_id = await resolve_customer_id(customer_name)
    if customer_id is None:
        return False, f"未找到客户: {customer_name}（请确认姓名或存在重名）"

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
    return True, results


async def get_suitable_products(risk_level: str, limit: int = 10) -> List[dict]:
    """
    适当性匹配产品查询（通过图谱 SUITABLE_FOR 关系）
    入参: 风险等级（R1-R5），返回不超过该等级的在售产品
    返回: [{product_name, product_code, product_type, risk_level, expected_return}]
    """
    # 映射等级数值
    level_order = {"R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}
    max_level = level_order.get(risk_level, 3)
    suitable_levels = [f"R{i}" for i in range(1, max_level + 1)]

    # 使用图谱 SUITABLE_FOR 关系查询（RiskLevel → Product）
    results = await neo4j.run_query(
        """
        MATCH (r:RiskLevel)-[:SUITABLE_FOR]->(p:Product)
        WHERE r.level IN $levels AND p.status = '在售'
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
