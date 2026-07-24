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
    适当性匹配产品查询（通过图谱 CustomerRiskLevel/ProductRiskLevel 关系）
    入参: 客户风险等级（C1-C5），返回不超过该等级的在售产品
    返回: [{product_name, product_code, product_type, risk_level, expected_return}]
    """
    # 映射等级数值（客户用 C1-C5，产品用 R1-R5，对应关系：C1↔R1, C2↔R2, ...）
    level_order = {"C1": 1, "C2": 2, "C3": 3, "C4": 4, "C5": 5,
                   "R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}
    max_level = level_order.get(risk_level, 3)
    # 适当性匹配：产品风险等级 <= 客户风险承受能力
    suitable_levels = [f"R{i}" for i in range(1, max_level + 1)]

    # 使用图谱关系查询：ProductRiskLevel → CustomerRiskLevel (SUITABLE_FOR)
    # 反向查找：给定客户风险等级 C3，找所有 R1/R2/R3 产品
    results = await neo4j.run_query(
        """
        MATCH (prl:ProductRiskLevel)-[:SUITABLE_FOR]->(crl:CustomerRiskLevel {level_code: $risk_level})
        MATCH (p:Product)-[:HAS_PRODUCT_RISK]->(prl)
        WHERE p.status = '在售'
        RETURN p.name AS product_name, p.code AS product_code,
               p.type AS product_type, p.risk_level AS risk_level,
               p.expected_return AS expected_return, p.min_amount AS min_amount
        ORDER BY p.expected_return DESC
        LIMIT $limit
        """,
        {"risk_level": risk_level if risk_level.startswith("C") else f"C{risk_level[1:]}",
         "limit": limit},
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
    返回: [{industry, product_count, total_value, percentage}]
    """
    customer_id = await resolve_customer_id(customer_name)
    if not customer_id:
        return []

    results = await neo4j.run_query(
        """
        MATCH (c:Customer {id: $cid})-[h:INVESTS_IN]->(p:Product)-[:BELONGS_TO]->(i:Industry)
        WITH c, i, COUNT(p) AS product_count, SUM(h.current_value) AS total_value
        WITH c, SUM(total_value) AS grand_total,
             COLLECT({industry: i.name, count: product_count, value: total_value}) AS industries
        UNWIND industries AS ind
        RETURN ind.industry AS industry,
               ind.count AS product_count,
               ind.value AS total_value,
               ROUND(ind.value / grand_total * 100, 2) AS percentage
        ORDER BY percentage DESC
        """,
        {"cid": customer_id},
    )
    for r in results:
        if r.get("total_value"):
            r["total_value"] = round(float(r["total_value"]), 2)
    return results


# ═══════════════════════════════════════════════════════════
# 图算法查询函数（P4-⑩）
# ═══════════════════════════════════════════════════════════

from app.tool.cypher_templates import (
    PRODUCT_CENTRALITY,
    CUSTOMER_COMMUNITY,
    SHORTEST_PATH,
    INDUSTRY_CONCENTRATION,
    TX_FREQUENCY_ANOMALY,
)


async def get_product_centrality(limit: int = 20) -> List[dict]:
    """
    产品持有中心性分析（Degree Centrality）
    返回被最多客户持有的产品排名
    """
    return await neo4j.run_query(
        PRODUCT_CENTRALITY.replace("LIMIT 20", f"LIMIT {limit}")
    )


async def get_customer_community(threshold: float = 0.3) -> List[dict]:
    """
    客户社区发现（基于 Jaccard 相似度）
    返回持仓相似度 >= threshold 的客户对
    """
    return await neo4j.run_query(
        CUSTOMER_COMMUNITY,
        {"threshold": threshold},
        limit=0,
    )


async def get_shortest_path(customer_1: str, customer_2: str) -> Optional[dict]:
    """
    查询两个客户之间的最短关联路径
    返回路径节点和关系类型
    """
    result = await neo4j.run_query(
        SHORTEST_PATH,
        {"customer_1": customer_1, "customer_2": customer_2},
        limit=1,
    )
    return result[0] if result else None


async def get_industry_concentration(limit: int = 50) -> List[dict]:
    """
    客户持仓集中度分析（Herfindahl-Hirschman Index）
    HHI >= 0.5: 高度集中, >= 0.3: 中度集中, < 0.3: 分散
    """
    return await neo4j.run_query(
        INDUSTRY_CONCENTRATION.replace("LIMIT 50", f"LIMIT {limit}")
    )


async def get_tx_frequency_anomaly(days: int = 7, threshold: int = 5) -> List[dict]:
    """
    交易频率异常检测
    返回近 N 天交易次数超过阈值的客户
    """
    return await neo4j.run_query(
        TX_FREQUENCY_ANOMALY,
        {"days": days, "threshold": threshold},
        limit=0,
    )
