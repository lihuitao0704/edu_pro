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


async def import_products(driver):
    """从 MySQL 导入产品数据，创建 Product 节点 + BELONGS_TO/MANAGED_BY 关系"""
    async with async_session_factory() as mysql_session:
        result = await mysql_session.execute(text("SELECT * FROM fin_product"))
        rows = result.fetchall()
        columns = result.keys()

    # 列名映射
    col_map = {c: i for i, c in enumerate(columns)}

    count = 0
    async with driver.session(database=settings.neo4j.database) as neo4j_session:
        for row in rows:
            row = list(row)
            product_id = row[col_map["id"]]
            product_code = row[col_map["product_code"]]
            product_name = row[col_map["product_name"]]
            product_type = row[col_map.get("product_type", -1)] or "混合型"
            risk_level = row[col_map.get("risk_level", -1)] or "R3"
            expected_return = float(row[col_map.get("expected_return", -1)] or 0)
            min_amount = float(row[col_map.get("min_amount", -1)] or 1000)
            fund_manager_name = row[col_map.get("fund_manager", -1)] or ""
            status = row[col_map.get("status", -1)] or "在售"

            # 创建产品节点
            await neo4j_session.run(
                """
                MERGE (p:Product {id: $product_id})
                SET p.code = $code, p.name = $name, p.type = $type,
                    p.risk_level = $risk_level, p.expected_return = $expected_return,
                    p.min_amount = $min_amount, p.fund_manager = $fm_name,
                    p.status = $status
                """,
                product_id=product_id,
                code=product_code,
                name=product_name,
                type=product_type,
                risk_level=risk_level,
                expected_return=expected_return,
                min_amount=min_amount,
                fm_name=fund_manager_name,
                status=status,
            )

            # 产品 → 风险等级 (SUITABLE_FOR)
            await neo4j_session.run(
                "MATCH (p:Product {id: $pid}), (r:RiskLevel {level: $level}) "
                "MERGE (p)-[:HAS_RISK_LEVEL]->(r)",
                pid=product_id, level=risk_level,
            )

            # 风险等级 → 产品 (HAS_PRODUCT，反向用于适当性查询)
            await neo4j_session.run(
                "MATCH (r:RiskLevel {level: $level}), (p:Product {id: $pid}) "
                "MERGE (r)-[:HAS_PRODUCT]->(p)",
                level=risk_level, pid=product_id,
            )

            # 产品 → 行业 (BELONGS_TO) — Mock 映射
            prefix = product_code[:3].upper()
            industry_id = PRODUCT_INDUSTRY_MAP.get(prefix, "IND001")
            await neo4j_session.run(
                "MATCH (p:Product {id: $pid}), (i:Industry {industry_id: $ind_id}) "
                "MERGE (p)-[:BELONGS_TO]->(i)",
                pid=product_id, ind_id=industry_id,
            )

            # 产品 → 基金经理 (MANAGED_BY) — Mock 轮询
            fm_index = product_id % len(MOCK_FUND_MANAGERS)
            fm_id = MOCK_FUND_MANAGERS[fm_index]["manager_id"]
            await neo4j_session.run(
                "MATCH (p:Product {id: $pid}), (fm:FundManager {manager_id: $fm_id}) "
                "MERGE (p)-[:MANAGED_BY]->(fm)",
                pid=product_id, fm_id=fm_id,
            )

            count += 1

    print(f"  ✅ 产品节点 ({count}) + 关联关系")


async def import_customers(driver):
    """从 MySQL 导入客户数据，创建 Customer 节点 + HAS_RISK_LEVEL 关系"""
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

    count = 0
    async with driver.session(database=settings.neo4j.database) as neo4j_session:
        for row in customers:
            customer_id = row[0]
            username = row[1]
            real_name = row[2] or username
            customer_level = row[4] or "普通"

            # 风险等级映射: C1-C5 → R1-R5
            assessed_level = risk_map.get(customer_id, "C3")
            risk_level = assessed_level.replace("C", "R") if assessed_level.startswith("C") else "R3"

            await neo4j_session.run(
                """
                MERGE (c:Customer {id: $customer_id})
                SET c.name = $name, c.username = $username,
                    c.customer_level = $level
                """,
                customer_id=customer_id, name=real_name,
                username=username, level=customer_level,
            )

            # 客户 → 风险等级
            await neo4j_session.run(
                "MATCH (c:Customer {id: $cid}), (r:RiskLevel {level: $level}) "
                "MERGE (c)-[:HAS_RISK_LEVEL]->(r)",
                cid=customer_id, level=risk_level,
            )

            count += 1

    print(f"  ✅ 客户节点 ({count}) + 风险等级关系")


async def import_holdings(driver):
    """从 MySQL 导入持仓数据，创建 INVESTS_IN 关系"""
    async with async_session_factory() as mysql_session:
        result = await mysql_session.execute(
            text("SELECT customer_id, product_id, shares, cost_amount, "
                 "current_value, profit_loss, profit_ratio "
                 "FROM fin_holdings WHERE status = '持有中'")
        )
        holdings = result.fetchall()

    count = 0
    async with driver.session(database=settings.neo4j.database) as neo4j_session:
        for row in holdings:
            await neo4j_session.run(
                """
                MATCH (c:Customer {id: $cid}), (p:Product {id: $pid})
                MERGE (c)-[h:INVESTS_IN]->(p)
                SET h.shares = $shares, h.cost_amount = $cost,
                    h.current_value = $value, h.profit_loss = $pl,
                    h.profit_ratio = $ratio
                """,
                cid=row[0], pid=row[1],
                shares=float(row[2] or 0),
                cost=float(row[3] or 0),
                value=float(row[4] or 0),
                pl=float(row[5] or 0),
                ratio=float(row[6] or 0),
            )
            count += 1

    print(f"  ✅ 持仓关系 ({count})")


async def show_stats(driver):
    """打印导入后的图谱统计"""
    async with driver.session(database=settings.neo4j.database) as session:
        # 节点统计
        for label in ["Customer", "Product", "RiskLevel", "Industry", "FundManager"]:
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


async def main():
    """主入口"""
    print("=" * 50)
    print("🚀 Neo4j 知识图谱数据导入")
    print("=" * 50)

    driver = get_neo4j_driver()

    # 先清空（开发阶段）
    print("\n[1/7] 清空旧数据...")
    async with driver.session(database=settings.neo4j.database) as session:
        await session.run("MATCH (n) DETACH DELETE n")
    print("  ✅ 已清空")

    # 按顺序导入
    print("\n[2/7] 导入风险等级...")
    await import_risk_levels(driver)

    print("\n[3/7] 导入 Mock 行业...")
    await import_mock_industries(driver)

    print("\n[4/7] 导入 Mock 基金经理...")
    await import_mock_managers(driver)

    print("\n[5/7] 导入产品数据 (MySQL → Neo4j)...")
    await import_products(driver)

    print("\n[6/7] 导入客户数据 (MySQL → Neo4j)...")
    await import_customers(driver)

    print("\n[6/7] 导入持仓关系 (MySQL → Neo4j)...")
    await import_holdings(driver)

    # 统计
    print("\n[7/7] 图谱统计:")
    await show_stats(driver)

    print("\n" + "=" * 50)
    print("✅ 导入完成！")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
