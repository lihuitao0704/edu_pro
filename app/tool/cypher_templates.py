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
MATCH (c:Customer {id: $customer_id})-[h:INVESTS_IN]->(p:Product)-[:BELONGS_TO]->(i:Industry)
WITH c, i, SUM(h.current_value) AS industry_value
WITH c, SUM(industry_value) AS total_value,
     COLLECT({industry: i.name, value: industry_value}) AS industries
UNWIND industries AS ind
RETURN ind.industry AS industry,
       ind.value AS industry_value,
       ROUND(ind.value / total_value * 100, 2) AS percentage
ORDER BY percentage DESC
"""

# 适当性匹配产品
SUITABLE_PRODUCTS = """
MATCH (pr:ProductRiskLevel)-[:SUITABLE_FOR]->(crl:CustomerRiskLevel)
WHERE crl.level_code = $risk_level
MATCH (p:Product)-[:HAS_PRODUCT_RISK]->(pr)
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
MATCH (c:Customer {id: $customer_id})-[:HAS_RISK_LEVEL]->(crl:CustomerRiskLevel)
RETURN crl.level_code AS risk_level
"""

# ═══════════════════════════════════════════════════════
# 多跳查询（GraphRAG 用）
# ═══════════════════════════════════════════════════════

# 查询：持有某行业产品且为某风险等级的所有客户
# 用途：场景测试 "持有新能源行业产品的C4级客户"
# 跳数：Customer → Product → Industry + Customer → CustomerRiskLevel（三跳）
CUSTOMERS_BY_INDUSTRY_AND_RISK = """
MATCH (c:Customer)-[:HAS_RISK_LEVEL]->(crl:CustomerRiskLevel)
MATCH (c)-[:INVESTS_IN]->(p:Product)-[:BELONGS_TO]->(i:Industry)
WHERE i.name CONTAINS $industry AND crl.level_code = $risk_level
RETURN c.id AS customer_id, c.name AS customer_name,
       c.customer_level AS customer_level,
       crl.level_code AS risk_level, crl.description AS risk_description,
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
# 在 name / description / level_code 字段中匹配关键词
GRAPH_ENTITY_SEARCH = """
MATCH (n)
WHERE (n.name CONTAINS $keyword
   OR n.description CONTAINS $keyword
   OR n.level_code CONTAINS $keyword)
  AND (n:Industry OR n:Product OR n:CustomerRiskLevel OR n:ProductRiskLevel OR n:Customer)
RETURN labels(n) AS labels, n.name AS name, n.level_code AS level,
       n.description AS description
LIMIT 10
"""

# 查询：全图谱概览（客户 → 客户风险等级 → 产品 → 行业）
FULL_GRAPH_OVERVIEW = """
MATCH (c:Customer)-[:HAS_RISK_LEVEL]->(crl:CustomerRiskLevel)
MATCH (c)-[:INVESTS_IN]->(p:Product)-[:BELONGS_TO]->(i:Industry)
RETURN c.id AS customer_id, c.name AS customer_name,
       c.customer_level AS customer_level,
       crl.level_code AS risk_level, crl.description AS risk_description,
       collect(DISTINCT {
           product_name: p.name, product_code: p.code,
           product_type: p.type, product_risk: p.risk_level,
           industry: i.name
       }) AS holdings
ORDER BY c.id
"""

# 查询：按风险等级聚合统计客户行业偏好
RISK_INDUSTRY_STATS = """
MATCH (c:Customer)-[:HAS_RISK_LEVEL]->(crl:CustomerRiskLevel)
MATCH (c)-[:INVESTS_IN]->(p:Product)-[:BELONGS_TO]->(i:Industry)
RETURN crl.level_code AS risk_level, crl.description AS risk_desc,
       i.name AS industry, count(DISTINCT c) AS customer_count,
       collect(DISTINCT c.name) AS customers
ORDER BY crl.level_code, customer_count DESC
"""

# ═══════════════════════════════════════════════════════════
# 图算法模板（P4-⑩）
# ═══════════════════════════════════════════════════════════

# 产品持有中心性：哪些产品被最多客户持有（Degree Centrality）
PRODUCT_CENTRALITY = """
MATCH (c:Customer)-[:INVESTS_IN]->(p:Product)
WITH p, count(c) AS holder_count,
     sum([ (c)-[:INVESTS_IN]->(p) | 1 ][0]) AS total_investments
RETURN p.name AS product_name, p.code AS product_code,
       p.type AS product_type, p.risk_level AS risk_level,
       holder_count,
       round(total_investments * 1.0 / holder_count, 2) AS avg_investments_per_customer
ORDER BY holder_count DESC
LIMIT 20
"""

# 客户社区发现：基于共同持仓的 Jaccard 相似度聚类
# 返回相似度 > 阈值的客户对
CUSTOMER_COMMUNITY = """
MATCH (c1:Customer)-[:INVESTS_IN]->(p:Product)<-[:INVESTS_IN]-(c2:Customer)
WHERE c1.id < c2.id
WITH c1, c2, collect(DISTINCT p) AS common_products
WITH c1, c2, common_products, size(common_products) AS common_count
// 计算 c1 的总产品数
MATCH (c1)-[:INVESTS_IN]->(p1:Product)
WITH c1, c2, common_products, common_count, count(DISTINCT p1) AS c1_product_count
// 计算 c2 的总产品数
MATCH (c2)-[:INVESTS_IN]->(p2:Product)
WITH c1, c2, common_count, c1_product_count, count(DISTINCT p2) AS c2_product_count
// 计算 Jaccard 相似度 = 交集 / 并集
WITH c1, c2, common_count,
     c1_product_count + c2_product_count - common_count AS union_size
WITH c1, c2, common_count,
     round(common_count * 1.0 / union_size, 3) AS jaccard_similarity
WHERE jaccard_similarity >= $threshold
RETURN c1.name AS customer_1, c1.id AS customer_1_id,
       c2.name AS customer_2, c2.id AS customer_2_id,
       common_count AS shared_products,
       jaccard_similarity
ORDER BY jaccard_similarity DESC
LIMIT 50
"""

# 两个客户之间的最短关联路径
SHORTEST_PATH = """
MATCH path = shortestPath(
    (c1:Customer)-[*..6]-(c2:Customer)
)
WHERE c1.name = $customer_1 AND c2.name = $customer_2
RETURN [n IN nodes(path) |
    CASE
        WHEN n:Customer THEN 'Customer:' + n.name
        WHEN n:Product THEN 'Product:' + n.name
        WHEN n:Employee THEN 'Employee:' + n.name
        ELSE labels(n)[0]
    END
] AS path_nodes,
       [r IN relationships(path) | type(r)] AS path_relations,
       length(path) AS path_length
"""

# 客户持仓集中度风险：Herfindahl 指数
# HHI = SUM(行业占比^2)，值越接近1表示越集中
INDUSTRY_CONCENTRATION = """
MATCH (c:Customer)-[h:INVESTS_IN]->(p:Product)-[:BELONGS_TO]->(i:Industry)
WITH c, i, SUM(h.current_value) AS industry_value
WITH c, SUM(industry_value) AS total_value,
     COLLECT({industry: i.name, value: industry_value}) AS industries
UNWIND industries AS ind
WITH c, total_value, ind,
     round(ind.value / total_value, 4) AS weight
WITH c, total_value,
     SUM(weight ^ 2) AS hhi_index,
     COLLECT({industry: ind.industry, weight: round(weight * 100, 1)}) AS breakdown
RETURN c.name AS customer_name,
       round(hhi_index, 4) AS hhi_index,
       CASE
           WHEN hhi_index >= 0.5 THEN '高度集中'
           WHEN hhi_index >= 0.3 THEN '中度集中'
           ELSE '分散'
       END AS risk_level,
       breakdown AS industry_breakdown
ORDER BY hhi_index DESC
LIMIT 50
"""

# 交易频率异常检测：近 N 天交易次数超过阈值的客户
TX_FREQUENCY_ANOMALY = """
MATCH (c:Customer)-[:MADE]->(t:Transaction)
WHERE t.timestamp >= datetime() - duration({days: $days})
WITH c, COUNT(t) AS tx_count,
     COLLECT(t.transaction_no) AS recent_transactions
WHERE tx_count >= $threshold
RETURN c.name AS customer_name, c.customer_level AS level,
       tx_count AS transaction_count,
       recent_transactions[0..5] AS sample_transactions
ORDER BY tx_count DESC
LIMIT 50
"""
