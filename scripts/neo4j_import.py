"""
Neo4j 知识图谱数据导入脚本
从 MySQL 读取产品/客户/持仓/风评数据，导入 Neo4j 构建图谱
包含 Mock 的行业、基金经理、市场数据

使用方式:
    cd 项目根目录
    python -m scripts.neo4j_import
    或
    python scripts/neo4j_import.py
"""

import asyncio
import sys
import os

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.config.database import async_session_factory, get_neo4j_driver
from app.config.settings import get_settings

settings = get_settings()


# ==================== Mock 数据 ====================

# 行业分类（Mock）
MOCK_INDUSTRIES = [
    {"industry_id": "IND001", "name": "消费"},
    {"industry_id": "IND002", "name": "医药"},
    {"industry_id": "IND003", "name": "科技"},
    {"industry_id": "IND004", "name": "金融"},
    {"industry_id": "IND005", "name": "新能源"},
    {"industry_id": "IND006", "name": "制造"},
]

# 基金经理（Mock）
MOCK_FUND_MANAGERS = [
    {"manager_id": "FM001", "name": "李明", "experience": "12年"},
    {"manager_id": "FM002", "name": "王芳", "experience": "8年"},
    {"manager_id": "FM003", "name": "张伟", "experience": "15年"},
    {"manager_id": "FM004", "name": "陈静", "experience": "6年"},
]

# 风险等级映射
RISK_LEVELS = ["R1", "R2", "R3", "R4", "R5"]
RISK_LABELS = {
    "R1": "保守型",
    "R2": "稳健型",
    "R3": "平衡型",
    "R4": "进取型",
    "R5": "激进型",
}

# 产品→行业 Mock 映射（按 product_code 前缀）
PRODUCT_INDUSTRY_MAP = {
    "TXB": "IND004",  # 天弘系列 → 金融
    "WF": "IND005",    #  Wealth系列 → 新能源
    "HH": "IND001",    # 混合系列 → 消费
    "GF": "IND006",    # 广发系列 → 制造
    "YF": "IND003",    # 易方达 → 科技
    "BF": "IND002",    # 债券系列 → 医药
    "HB": "IND004",    # 货币系列 → 金融
}

# 市场（Mock）
MOCK_MARKETS = [
    {"market_id": "MKT001", "name": "上海证券交易所"},
    {"market_id": "MKT002", "name": "深圳证券交易所"},
    {"market_id": "MKT003", "name": "北京证券交易所"},
    {"market_id": "MKT004", "name": "场外市场"},
]

# 产品→市场 Mock 映射（按 product_code 前缀）
PRODUCT_MARKET_MAP = {
    "TXB": "MKT004",  # 天弘（货币/债券）→ 场外
    "WF": "MKT001",    # Wealth系列 → 上交所
    "HH": "MKT002",    # 混合系列 → 深交所
    "GF": "MKT001",    # 广发系列 → 上交所
    "YF": "MKT002",    # 易方达 → 深交所
    "BF": "MKT004",    # 债券系列 → 场外
    "HB": "MKT004",    # 货币系列 → 场外
}


async def import_risk_levels(driver):
    """导入风险等级节点"""
    async with driver.session(database=settings.neo4j.database) as session:
        # 创建 R1-R5 节点
        for level in RISK_LEVELS:
            await session.run(
                "MERGE (r:RiskLevel {level: $level}) "
                "SET r.description = $desc",
                level=level, desc=RISK_LABELS[level],
            )
        print("  ✅ 风险等级节点 (5)")


async def import_mock_industries(driver):
    """导入 Mock 行业节点"""
    async with driver.session(database=settings.neo4j.database) as session:
        for ind in MOCK_INDUSTRIES:
            await session.run(
                "MERGE (i:Industry {industry_id: $id}) SET i.name = $name",
                id=ind["industry_id"], name=ind["name"],
            )
        print(f"  ✅ 行业节点 ({len(MOCK_INDUSTRIES)})")


async def import_mock_managers(driver):
    """导入 Mock 基金经理节点"""
    async with driver.session(database=settings.neo4j.database) as session:
        for fm in MOCK_FUND_MANAGERS:
            await session.run(
                "MERGE (fm:FundManager {manager_id: $id}) "
                "SET fm.name = $name, fm.experience = $exp",
                id=fm["manager_id"], name=fm["name"], exp=fm["experience"],
            )
        print(f"  ✅ 基金经理节点 ({len(MOCK_FUND_MANAGERS)})")


async def import_mock_markets(driver):
    """导入 Mock 市场节点"""
    async with driver.session(database=settings.neo4j.database) as session:
        for mkt in MOCK_MARKETS:
            await session.run(
                "MERGE (m:Market {market_id: $id}) SET m.name = $name",
                id=mkt["market_id"], name=mkt["name"],
            )
        print(f"  ✅ 市场节点 ({len(MOCK_MARKETS)})")


async def import_products(driver):
    """从 MySQL 导入产品数据，创建 Product 节点 + BELONGS_TO/MANAGED_BY 关系（批量导入优化）"""
    async with async_session_factory() as mysql_session:
        result = await mysql_session.execute(text("SELECT * FROM fin_product"))
        rows = result.fetchall()
        columns = result.keys()

    # 列名映射
    col_map = {c: i for i, c in enumerate(columns)}

    # 安全取值辅助函数：列不存在时返回 None 而非错误值
    def safe_get(row, col_name, default=None):
        idx = col_map.get(col_name)
        if idx is None:
            return default
        val = row[idx]
        return val if val is not None else default

    # 收集批量数据
    products_data = []
    industry_set = set()
    relations_data = {
        "risk_level": [],
        "has_product": [],
        "belongs_to": [],
        "managed_by": [],
        "suitable_for": [],
        "traded_on": [],
    }

    for row in rows:
        row = list(row)
        product_id = row[col_map["id"]]
        product_code = row[col_map["product_code"]]
        product_name = row[col_map["product_name"]]
        product_type = safe_get(row, "product_type", "混合型")
        risk_level = safe_get(row, "risk_level", "R3")
        expected_return = float(safe_get(row, "expected_return", 0))
        min_amount = float(safe_get(row, "min_amount", 1000))
        fund_manager_name = safe_get(row, "fund_manager", "")
        status = safe_get(row, "status", "在售")

        # 收集产品节点数据
        products_data.append({
            "product_id": product_id,
            "code": product_code,
            "name": product_name,
            "type": product_type,
            "risk_level": risk_level,
            "expected_return": expected_return,
            "min_amount": min_amount,
            "fm_name": fund_manager_name,
            "status": status,
        })

        # 收集风险等级关系
        relations_data["risk_level"].append({"pid": product_id, "level": risk_level})
        relations_data["has_product"].append({"pid": product_id, "level": risk_level})

        # 处理行业（从数据库读取真实行业，修复 2.5）
        industry_name = safe_get(row, "industry", "")
        prefix = product_code[:3].upper()
        if industry_name:
            industry_id = f"IND_{industry_name}"
            industry_set.add((industry_id, industry_name))
        else:
            # 兜底：使用 Mock 映射
            industry_id = PRODUCT_INDUSTRY_MAP.get(prefix, "IND001")
        relations_data["belongs_to"].append({"pid": product_id, "ind_id": industry_id})

        # 收集基金经理关系（Mock 轮询）
        fm_index = product_id % len(MOCK_FUND_MANAGERS)
        fm_id = MOCK_FUND_MANAGERS[fm_index]["manager_id"]
        relations_data["managed_by"].append({"pid": product_id, "fm_id": fm_id})

        # 收集适当性关系
        relations_data["suitable_for"].append({"pid": product_id, "level": risk_level})

        # 收集市场关系（Mock 映射）
        market_id = PRODUCT_MARKET_MAP.get(prefix, "MKT004")
        relations_data["traded_on"].append({"pid": product_id, "mid": market_id})

    # 批量执行 Neo4j 操作
    async with driver.session(database=settings.neo4j.database) as neo4j_session:
        # 1. 批量创建产品节点（UNWIND优化）
        if products_data:
            await neo4j_session.run(
                """
                UNWIND $products AS p
                MERGE (prod:Product {id: p.product_id})
                SET prod.code = p.code, prod.name = p.name, prod.type = p.type,
                    prod.risk_level = p.risk_level, prod.expected_return = p.expected_return,
                    prod.min_amount = p.min_amount, prod.fund_manager = p.fm_name,
                    prod.status = p.status
                """,
                products=products_data,
            )

        # 2. 批量创建/合并行业节点
        if industry_set:
            await neo4j_session.run(
                """
                UNWIND $industries AS ind
                MERGE (i:Industry {industry_id: ind.ind_id})
                SET i.name = ind.name
                """,
                industries=[{"ind_id": ind_id, "name": name} for ind_id, name in industry_set],
            )

        # 3. 批量创建关系（UNWIND优化）
        batch_size = 1000

        # 产品→风险等级
        for i in range(0, len(relations_data["risk_level"]), batch_size):
            batch = relations_data["risk_level"][i:i+batch_size]
            await neo4j_session.run(
                """
                UNWIND $relations AS rel
                MATCH (p:Product {id: rel.pid}), (r:RiskLevel {level: rel.level})
                MERGE (p)-[:HAS_RISK_LEVEL]->(r)
                """,
                relations=batch,
            )

        # 风险等级→产品（反向）
        for i in range(0, len(relations_data["has_product"]), batch_size):
            batch = relations_data["has_product"][i:i+batch_size]
            await neo4j_session.run(
                """
                UNWIND $relations AS rel
                MATCH (r:RiskLevel {level: rel.level}), (p:Product {id: rel.pid})
                MERGE (r)-[:HAS_PRODUCT]->(p)
                """,
                relations=batch,
            )

        # 产品→行业
        for i in range(0, len(relations_data["belongs_to"]), batch_size):
            batch = relations_data["belongs_to"][i:i+batch_size]
            await neo4j_session.run(
                """
                UNWIND $relations AS rel
                MATCH (p:Product {id: rel.pid}), (i:Industry {industry_id: rel.ind_id})
                MERGE (p)-[:BELONGS_TO]->(i)
                """,
                relations=batch,
            )

        # 产品→基金经理
        for i in range(0, len(relations_data["managed_by"]), batch_size):
            batch = relations_data["managed_by"][i:i+batch_size]
            await neo4j_session.run(
                """
                UNWIND $relations AS rel
                MATCH (p:Product {id: rel.pid}), (fm:FundManager {manager_id: rel.fm_id})
                MERGE (p)-[:MANAGED_BY]->(fm)
                """,
                relations=batch,
            )

        # 风险等级→产品（适当性）
        for i in range(0, len(relations_data["suitable_for"]), batch_size):
            batch = relations_data["suitable_for"][i:i+batch_size]
            await neo4j_session.run(
                """
                UNWIND $relations AS rel
                MATCH (r:RiskLevel {level: rel.level}), (p:Product {id: rel.pid})
                MERGE (r)-[:SUITABLE_FOR]->(p)
                """,
                relations=batch,
            )

        # 产品→市场
        for i in range(0, len(relations_data["traded_on"]), batch_size):
            batch = relations_data["traded_on"][i:i+batch_size]
            await neo4j_session.run(
                """
                UNWIND $relations AS rel
                MATCH (p:Product {id: rel.pid}), (m:Market {market_id: rel.mid})
                MERGE (p)-[:TRADED_ON]->(m)
                """,
                relations=batch,
            )

    print(f"  ✅ 产品节点 ({len(products_data)}) + 关联关系（批量导入）")


async def import_customers(driver):
    """从 MySQL 导入客户数据，创建 Customer 节点 + HAS_RISK_LEVEL 关系（批量导入优化）"""
    async with async_session_factory() as mysql_session:
        # 查询所有客户
        result = await mysql_session.execute(
            text("SELECT id, username, real_name, user_type, customer_level "
                 "FROM sys_user WHERE user_type = 'CUSTOMER'")
        )
        customers = result.fetchall()

        # 查询客户风险等级（从风评表取最新的）
        risk_result = await mysql_session.execute(
            text("SELECT customer_id, risk_level FROM fin_risk_assessment "
                 "ORDER BY create_time DESC")
        )
        risk_map = {}
        for row in risk_result.fetchall():
            cid = row[0]
            if cid not in risk_map:
                risk_map[cid] = row[1]

    # 收集批量数据
    customers_data = []
    risk_relations = []

    for row in customers:
        customer_id = row[0]
        username = row[1]
        real_name = row[2] or username
        customer_level = row[4] or "普通"

        # 风险等级映射: C1-C5 → R1-R5
        assessed_level = risk_map.get(customer_id, "C3")
        risk_level = assessed_level.replace("C", "R") if assessed_level.startswith("C") else "R3"

        customers_data.append({
            "customer_id": customer_id,
            "name": real_name,
            "username": username,
            "level": customer_level,
        })
        risk_relations.append({
            "cid": customer_id,
            "level": risk_level,
        })

    # 批量执行 Neo4j 操作
    async with driver.session(database=settings.neo4j.database) as neo4j_session:
        # 1. 批量创建客户节点（UNWIND优化）
        if customers_data:
            await neo4j_session.run(
                """
                UNWIND $customers AS c
                MERGE (cust:Customer {id: c.customer_id})
                SET cust.name = c.name, cust.username = c.username,
                    cust.customer_level = c.level
                """,
                customers=customers_data,
            )

        # 2. 批量创建客户→风险等级关系（UNWIND优化）
        if risk_relations:
            await neo4j_session.run(
                """
                UNWIND $relations AS rel
                MATCH (c:Customer {id: rel.cid}), (r:RiskLevel {level: rel.level})
                MERGE (c)-[:HAS_RISK_LEVEL]->(r)
                """,
                relations=risk_relations,
            )

    print(f"  ✅ 客户节点 ({len(customers_data)}) + 风险等级关系（批量导入）")


async def import_holdings(driver):
    """从 MySQL 导入持仓数据，创建 INVESTS_IN 关系（批量导入优化）"""
    async with async_session_factory() as mysql_session:
        result = await mysql_session.execute(
            text("SELECT customer_id, product_id, shares, cost_amount, "
                 "current_value, profit_loss, profit_ratio "
                 "FROM fin_holdings WHERE status = '持有中'")
        )
        holdings = result.fetchall()

    # 收集批量数据
    holdings_data = []
    for row in holdings:
        holdings_data.append({
            "cid": row[0],
            "pid": row[1],
            "shares": float(row[2] or 0),
            "cost": float(row[3] or 0),
            "value": float(row[4] or 0),
            "pl": float(row[5] or 0),
            "ratio": float(row[6] or 0),
        })

    # 批量执行 Neo4j 操作
    async with driver.session(database=settings.neo4j.database) as neo4j_session:
        if holdings_data:
            # 批量创建/更新持仓关系（UNWIND优化）
            await neo4j_session.run(
                """
                UNWIND $holdings AS h
                MATCH (c:Customer {id: h.cid}), (p:Product {id: h.pid})
                MERGE (c)-[inv:INVESTS_IN]->(p)
                SET inv.shares = h.shares, inv.cost_amount = h.cost,
                    inv.current_value = h.value, inv.profit_loss = h.pl,
                    inv.profit_ratio = h.ratio
                """,
                holdings=holdings_data,
            )

    print(f"  ✅ 持仓关系 ({len(holdings_data)})（批量导入）")


async def show_stats(driver):
    """打印导入后的图谱统计"""
    async with driver.session(database=settings.neo4j.database) as session:
        # 节点统计
        for label in ["Customer", "Product", "RiskLevel", "Industry", "FundManager", "Market"]:
            result = await session.run(f"MATCH (n:{label}) RETURN count(n) AS cnt")
            data = await result.single()
            print(f"  {label}: {data['cnt']} 个节点")

        # 关系统计
        result = await session.run(
            "MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS cnt ORDER BY cnt DESC"
        )
        records = await result.data()
        print("  关系:")
        for rec in records:
            print(f"    {rec['type']}: {rec['cnt']} 条")


async def create_indexes(driver):
    """创建索引（幂等），加速后续 MERGE 和查询"""
    index_statements = [
        "CREATE INDEX IF NOT EXISTS FOR (n:Customer) ON (n.id)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Product) ON (n.id)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Product) ON (n.code)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Industry) ON (n.industry_id)",
        "CREATE INDEX IF NOT EXISTS FOR (n:RiskLevel) ON (n.level)",
        "CREATE INDEX IF NOT EXISTS FOR (n:FundManager) ON (n.manager_id)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Market) ON (n.market_id)",
    ]
    async with driver.session(database=settings.neo4j.database) as session:
        for stmt in index_statements:
            await session.run(stmt)
    print(f"  ✅ 索引 ({len(index_statements)})")


async def main():
    """主入口"""
    print("=" * 50)
    print("🚀 Neo4j 知识图谱数据导入")
    print("=" * 50)

    # 安全检查：必须传 --confirm 才执行清空操作
    if "--confirm" not in sys.argv:
        print("\n⚠️  警告：此脚本将清空 Neo4j 数据库中的全部数据后重新导入。")
        print(f"   目标数据库: {settings.neo4j.database}")
        print("\n   如需继续，请添加 --confirm 参数：")
        print("   python -m scripts.neo4j_import --confirm")
        sys.exit(1)

    driver = get_neo4j_driver()

    try:
        # 先清空（开发阶段）
        print("\n[1/9] 清空旧数据...")
        async with driver.session(database=settings.neo4j.database) as session:
            await session.run("MATCH (n) DETACH DELETE n")
        print("  ✅ 已清空")

        # 创建索引（幂等，加速后续 MERGE 和查询）
        print("\n[2/9] 创建索引...")
        await create_indexes(driver)

        # 按顺序导入
        print("\n[3/9] 导入风险等级...")
        await import_risk_levels(driver)

        print("\n[4/9] 导入 Mock 行业...")
        await import_mock_industries(driver)

        print("\n[5/9] 导入 Mock 基金经理...")
        await import_mock_managers(driver)

        print("\n[6/9] 导入 Mock 市场...")
        await import_mock_markets(driver)

        print("\n[7/9] 导入产品数据 (MySQL → Neo4j)...")
        await import_products(driver)

        print("\n[8/9] 导入客户数据 (MySQL → Neo4j)...")
        await import_customers(driver)

        print("\n[9/9] 导入持仓关系 (MySQL → Neo4j)...")
        await import_holdings(driver)

        # 统计
        print("\n图谱统计:")
        await show_stats(driver)

        print("\n" + "=" * 50)
        print("✅ 导入完成！")
        print("=" * 50)
    finally:
        # 确保连接池被清理
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
