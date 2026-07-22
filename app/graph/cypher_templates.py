"""Cypher 查询模板"""

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
