"""Cypher 查询模板"""

# ═══════════════════════════════════════════════════════
# 基础查询（已有）
# ═══════════════════════════════════════════════════════

# 客户持仓产品
CUSTOMER_PRODUCTS = """
MATCH (c:Customer {id: $customer_id})-[:INVESTS_IN]->(p:Product)
RETURN p.code AS product_code, p.type AS product_type, p.risk_level AS risk_level
LIMIT 20
"""

# 产品所属行业
PRODUCT_INDUSTRY = """
MATCH (p:Product {code: $product_code})-[:BELONGS_TO]->(i:Industry)
RETURN i.name AS industry
"""

# 客户持仓行业分布
INDUSTRY_DISTRIBUTION = """
MATCH (c:Customer {id: $customer_id})-[:INVESTS_IN]->(p:Product)-[:BELONGS_TO]->(i:Industry)
RETURN i.name AS industry, count(p) AS product_count
ORDER BY product_count DESC
"""

# 适当性匹配产品
SUITABLE_PRODUCTS = """
MATCH (r:RiskLevel {level: $risk_level})-[:HAS_PRODUCT]->(p:Product)
WHERE p.status = '在售'
RETURN p.code AS product_code, p.type AS product_type, p.expected_return AS expected_return
LIMIT 20
"""

# 共同持仓
COMMON_HOLDINGS = """
MATCH (c1:Customer {id: $id1})-[:INVESTS_IN]->(p:Product)<-[:INVESTS_IN]-(c2:Customer {id: $id2})
RETURN p.code AS product_code, p.type AS product_type
"""

# 产品-基金经理关系
PRODUCT_MANAGER = """
MATCH (p:Product {code: $product_code})-[:MANAGED_BY]->(fm:FundManager)
RETURN fm.name AS manager_name, fm.experience AS experience
"""

# 客户风险等级关联
CUSTOMER_RISK = """
MATCH (c:Customer {id: $customer_id})-[:HAS_RISK_LEVEL]->(r:RiskLevel)
RETURN r.level AS risk_level
"""

# ═══════════════════════════════════════════════════════
# 多跳查询（GraphRAG 用）
# ═══════════════════════════════════════════════════════

# 查询：持有某行业产品且为某风险等级的所有客户
# 用途：场景测试 "持有新能源行业产品的C4级客户"
# 跳数：Customer → Product → Industry + Customer → RiskLevel（三跳）
CUSTOMERS_BY_INDUSTRY_AND_RISK = """
MATCH (c:Customer)-[:HAS_RISK_LEVEL]->(r:RiskLevel)
MATCH (c)-[:INVESTS_IN]->(p:Product)-[:BELONGS_TO]->(i:Industry)
WHERE i.name CONTAINS $industry AND r.level = $risk_level
RETURN c.id AS customer_id, c.name AS customer_name,
       c.customer_level AS customer_level,
       r.level AS risk_level, r.description AS risk_description,
       i.name AS industry_name,
       collect(DISTINCT {code: p.code, name: p.name, type: p.type, risk: p.risk_level}) AS holdings
ORDER BY c.id
"""

# 查询：某客户持仓产品的同行业其他产品（推荐用）
# 跳数：Customer → Product → Industry ← 其他Product（二跳扩展）
PEER_PRODUCTS_BY_INDUSTRY = """
MATCH (c:Customer {id: $customer_id})-[:INVESTS_IN]->(:Product)-[:BELONGS_TO]->(i:Industry)
MATCH (i)<-[:BELONGS_TO]-(peer:Product)
WHERE NOT (c)-[:INVESTS_IN]->(peer) AND peer.status = '在售'
RETURN peer.code AS code, peer.name AS name, peer.type AS type,
       peer.risk_level AS risk_level, peer.expected_return AS expected_return,
       i.name AS industry
LIMIT 20
"""

# 查询：图谱实体模糊搜索（实体提取阶段用）
# 在 name / description / level 字段中匹配关键词
GRAPH_ENTITY_SEARCH = """
MATCH (n)
WHERE (n.name CONTAINS $keyword
   OR n.description CONTAINS $keyword
   OR n.level CONTAINS $keyword)
  AND (n:Industry OR n:Product OR n:RiskLevel OR n:Customer)
RETURN labels(n) AS labels, n.name AS name, n.level AS level,
       n.description AS description
LIMIT 10
"""

# 查询：全图谱概览（客户 → 风险等级 → 产品 → 行业）
FULL_GRAPH_OVERVIEW = """
MATCH (c:Customer)-[:HAS_RISK_LEVEL]->(r:RiskLevel)
MATCH (c)-[:INVESTS_IN]->(p:Product)-[:BELONGS_TO]->(i:Industry)
RETURN c.id AS customer_id, c.name AS customer_name,
       c.customer_level AS customer_level,
       r.level AS risk_level, r.description AS risk_description,
       collect(DISTINCT {
           product_name: p.name, product_code: p.code,
           product_type: p.type, product_risk: p.risk_level,
           industry: i.name
       }) AS holdings
ORDER BY c.id
"""

# 查询：按风险等级聚合统计客户行业偏好
RISK_INDUSTRY_STATS = """
MATCH (c:Customer)-[:HAS_RISK_LEVEL]->(r:RiskLevel)
MATCH (c)-[:INVESTS_IN]->(p:Product)-[:BELONGS_TO]->(i:Industry)
RETURN r.level AS risk_level, r.description AS risk_desc,
       i.name AS industry, count(DISTINCT c) AS customer_count,
       collect(DISTINCT c.name) AS customers
ORDER BY r.level, customer_count DESC
"""
