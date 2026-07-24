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

# 风险等级映射（客户用 C1-C5，产品用 R1-R5）
CUSTOMER_RISK_LEVELS = ["C1", "C2", "C3", "C4", "C5"]
PRODUCT_RISK_LEVELS = ["R1", "R2", "R3", "R4", "R5"]
CUSTOMER_RISK_LABELS = {
    "C1": "保守型",
    "C2": "稳健型",
    "C3": "平衡型",
    "C4": "进取型",
    "C5": "激进型",
}
PRODUCT_RISK_LABELS = {
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


async def import_customer_risk_levels(driver):
    """导入客户风险等级节点 (C1-C5)"""
    async with driver.session(database=settings.neo4j.database) as session:
        for level in CUSTOMER_RISK_LEVELS:
            await session.run(
                "MERGE (r:CustomerRiskLevel {level_code: $level}) "
                "SET r.description = $desc",
                level=level, desc=CUSTOMER_RISK_LABELS[level],
            )
        print("  [OK] 客户风险等级节点 (C1-C5, 5个)")


async def import_product_risk_levels(driver):
    """导入产品风险等级节点 (R1-R5)"""
    async with driver.session(database=settings.neo4j.database) as session:
        for level in PRODUCT_RISK_LEVELS:
            await session.run(
                "MERGE (r:ProductRiskLevel {level_code: $level}) "
                "SET r.description = $desc",
                level=level, desc=PRODUCT_RISK_LABELS[level],
            )
        print("  [OK] 产品风险等级节点 (R1-R5, 5个)")


async def import_mock_industries(driver):
    """导入 Mock 行业节点"""
    async with driver.session(database=settings.neo4j.database) as session:
        for ind in MOCK_INDUSTRIES:
            await session.run(
                "MERGE (i:Industry {industry_id: $id}) SET i.name = $name",
                id=ind["industry_id"], name=ind["name"],
            )
        print(f"  [OK] 行业节点 ({len(MOCK_INDUSTRIES)})")


async def import_mock_managers(driver):
    """导入 Mock 基金经理节点"""
    async with driver.session(database=settings.neo4j.database) as session:
        for fm in MOCK_FUND_MANAGERS:
            await session.run(
                "MERGE (fm:FundManager {manager_id: $id}) "
                "SET fm.name = $name, fm.experience = $exp",
                id=fm["manager_id"], name=fm["name"], exp=fm["experience"],
            )
        print(f"  [OK] 基金经理节点 ({len(MOCK_FUND_MANAGERS)})")


async def import_mock_markets(driver):
    """导入 Mock 市场节点"""
    async with driver.session(database=settings.neo4j.database) as session:
        for mkt in MOCK_MARKETS:
            await session.run(
                "MERGE (m:Market {market_id: $id}) SET m.name = $name",
                id=mkt["market_id"], name=mkt["name"],
            )
        print(f"  [OK] 市场节点 ({len(MOCK_MARKETS)})")


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
        "product_risk_level": [],
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

        # 收集产品风险等级关系（Product → ProductRiskLevel）
        relations_data["product_risk_level"].append({"pid": product_id, "level": risk_level})

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

        # 产品→产品风险等级
        for i in range(0, len(relations_data["product_risk_level"]), batch_size):
            batch = relations_data["product_risk_level"][i:i+batch_size]
            await neo4j_session.run(
                """
                UNWIND $relations AS rel
                MATCH (p:Product {id: rel.pid}), (r:ProductRiskLevel {level_code: rel.level})
                MERGE (p)-[:HAS_PRODUCT_RISK]->(r)
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

        # 产品适当性匹配（ProductRiskLevel → CustomerRiskLevel）
        for i in range(0, len(relations_data["suitable_for"]), batch_size):
            batch = relations_data["suitable_for"][i:i+batch_size]
            await neo4j_session.run(
                """
                UNWIND $relations AS rel
                MATCH (pr:ProductRiskLevel {level_code: rel.level}), (cr:CustomerRiskLevel {level_code: rel.level})
                MERGE (pr)-[:SUITABLE_FOR {allowed_customer_levels: [rel.level]}]->(cr)
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

    print(f"  [OK] 产品节点 ({len(products_data)}) + 关联关系（批量导入）")


async def import_customers(driver):
    """从 MySQL 导入客户数据，创建 Customer 节点 + HAS_RISK_LEVEL 关系（批量导入优化）"""
    async with async_session_factory() as mysql_session:
        # 查询所有客户（补充 education, occupation, age, balance 等字段）
        result = await mysql_session.execute(
            text("SELECT id, username, real_name, user_type, customer_level, "
                 "education, occupation, age, balance, phone, email "
                 "FROM sys_user WHERE user_type = 'CUSTOMER'")
        )
        customers = result.fetchall()

        # 查询客户风险等级（从风评表取最新的）
        risk_result = await mysql_session.execute(
            text("SELECT customer_id, risk_level, total_score, assessment_date, valid_until "
                 "FROM fin_risk_assessment ORDER BY create_time DESC")
        )
        risk_map = {}
        for row in risk_result.fetchall():
            cid = row[0]
            if cid not in risk_map:
                risk_map[cid] = {
                    "risk_level": row[1],
                    "risk_score": row[2],
                    "assessment_date": str(row[3]) if row[3] else None,
                    "valid_until": str(row[4]) if row[4] else None,
                }

        # 查询客户画像数据
        profile_result = await mysql_session.execute(
            text("SELECT customer_id, total_assets, investment_experience, "
                 "annual_income_range, risk_flag, confidence_score, "
                 "basic_score, experience_score, risk_pref_score, behavior_score "
                 "FROM fin_customer_profile")
        )
        profile_map = {}
        for row in profile_result.fetchall():
            profile_map[row[0]] = {
                "total_assets": float(row[1]) if row[1] else 0,
                "investment_experience": row[2] or "",
                "annual_income_range": row[3] or "",
                "risk_flag": row[4] or "",
                "confidence_score": float(row[5]) if row[5] else 0,
                "basic_score": float(row[6]) if row[6] else 0,
                "experience_score": float(row[7]) if row[7] else 0,
                "risk_pref_score": float(row[8]) if row[8] else 0,
                "behavior_score": float(row[9]) if row[9] else 0,
            }

    # 收集批量数据
    customers_data = []
    risk_relations = []

    for row in customers:
        customer_id = row[0]
        username = row[1]
        real_name = row[2] or username
        customer_level = row[4] or "普通"
        education = row[5] or ""
        occupation = row[6] or ""
        age = row[7]
        balance = float(row[8]) if row[8] else 0
        phone = row[9] or ""
        email = row[10] or ""

        # 风险等级：直接使用 C1-C5 编码（不再转换为 R1-R5）
        risk_info = risk_map.get(customer_id, {})
        assessed_level = risk_info.get("risk_level", "C3")
        risk_level = assessed_level if assessed_level.startswith("C") else f"C{assessed_level.replace('R', '')}"

        # 画像数据
        profile = profile_map.get(customer_id, {})

        customers_data.append({
            "customer_id": customer_id,
            "name": real_name,
            "username": username,
            "level": customer_level,
            "education": education,
            "occupation": occupation,
            "age": age,
            "balance": balance,
            "phone": phone,
            "email": email,
            "total_assets": profile.get("total_assets", 0),
            "investment_experience": profile.get("investment_experience", ""),
            "annual_income_range": profile.get("annual_income_range", ""),
            "risk_score": risk_info.get("risk_score", 0),
            "assessment_date": risk_info.get("assessment_date"),
            "valid_until": risk_info.get("valid_until"),
            "risk_flag": profile.get("risk_flag", ""),
            "confidence_score": profile.get("confidence_score", 0),
            "basic_score": profile.get("basic_score", 0),
            "experience_score": profile.get("experience_score", 0),
            "risk_pref_score": profile.get("risk_pref_score", 0),
            "behavior_score": profile.get("behavior_score", 0),
        })
        risk_relations.append({
            "cid": customer_id,
            "level": risk_level,
        })

    # 批量执行 Neo4j 操作
    async with driver.session(database=settings.neo4j.database) as neo4j_session:
        # 1. 批量创建客户节点（UNWIND优化，包含画像属性）
        if customers_data:
            await neo4j_session.run(
                """
                UNWIND $customers AS c
                MERGE (cust:Customer {id: c.customer_id})
                SET cust.name = c.name, cust.username = c.username,
                    cust.customer_level = c.level,
                    cust.education = c.education, cust.occupation = c.occupation,
                    cust.age = c.age, cust.balance = c.balance,
                    cust.phone = c.phone, cust.email = c.email,
                    cust.total_assets = c.total_assets,
                    cust.investment_experience = c.investment_experience,
                    cust.annual_income_range = c.annual_income_range,
                    cust.risk_score = c.risk_score,
                    cust.assessment_date = c.assessment_date,
                    cust.valid_until = c.valid_until,
                    cust.risk_flag = c.risk_flag,
                    cust.confidence_score = c.confidence_score,
                    cust.basic_score = c.basic_score,
                    cust.experience_score = c.experience_score,
                    cust.risk_pref_score = c.risk_pref_score,
                    cust.behavior_score = c.behavior_score
                """,
                customers=customers_data,
            )

        # 2. 批量创建客户→客户风险等级关系（UNWIND优化）
        if risk_relations:
            await neo4j_session.run(
                """
                UNWIND $relations AS rel
                MATCH (c:Customer {id: rel.cid}), (r:CustomerRiskLevel {level_code: rel.level})
                MERGE (c)-[:HAS_RISK_LEVEL]->(r)
                """,
                relations=risk_relations,
            )

    print(f"  [OK] 客户节点 ({len(customers_data)}) + 画像属性 + 风险等级关系（批量导入）")


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

    print(f"  [OK] 持仓关系 ({len(holdings_data)})（批量导入）")


async def import_transactions(driver):
    """从 MySQL 导入交易流水数据，创建 Transaction 节点 + MADE/ON_PRODUCT 关系（批量导入优化）"""
    async with async_session_factory() as mysql_session:
        result = await mysql_session.execute(
            text("SELECT transaction_no, customer_id, product_id, transaction_type, "
                 "amount, shares, nav, fee, status, operator_id, remark, create_time "
                 "FROM fin_transaction ORDER BY create_time ASC")
        )
        transactions = result.fetchall()

    # 收集批量数据
    tx_data = []
    made_relations = []
    on_product_relations = []

    for row in transactions:
        tx_no = row[0]
        customer_id = row[1]
        product_id = row[2]
        tx_type = row[3] or ""
        amount = float(row[4]) if row[4] else 0
        shares = float(row[5]) if row[5] else 0
        nav = float(row[6]) if row[6] else 0
        fee = float(row[7]) if row[7] else 0
        status = row[8] or ""
        operator_id = row[9]
        remark = row[10] or ""
        create_time = str(row[11]) if row[11] else ""

        tx_data.append({
            "tx_no": tx_no,
            "tx_type": tx_type,
            "amount": amount,
            "shares": shares,
            "nav": nav,
            "fee": fee,
            "status": status,
            "operator_id": operator_id,
            "remark": remark,
            "create_time": create_time,
        })
        made_relations.append({"cid": customer_id, "tx_no": tx_no})
        on_product_relations.append({"tx_no": tx_no, "pid": product_id})

    # 批量执行 Neo4j 操作
    async with driver.session(database=settings.neo4j.database) as neo4j_session:
        # 1. 批量创建 Transaction 节点
        if tx_data:
            await neo4j_session.run(
                """
                UNWIND $transactions AS t
                MERGE (tx:Transaction {transaction_no: t.tx_no})
                SET tx.type = t.tx_type, tx.amount = t.amount,
                    tx.shares = t.shares, tx.nav = t.nav, tx.fee = t.fee,
                    tx.status = t.status, tx.operator_id = t.operator_id,
                    tx.remark = t.remark, tx.timestamp = t.create_time
                """,
                transactions=tx_data,
            )

        batch_size = 1000

        # 2. 批量创建 MADE 关系（Customer → Transaction）
        for i in range(0, len(made_relations), batch_size):
            batch = made_relations[i:i+batch_size]
            await neo4j_session.run(
                """
                UNWIND $relations AS rel
                MATCH (c:Customer {id: rel.cid}), (t:Transaction {transaction_no: rel.tx_no})
                MERGE (c)-[:MADE]->(t)
                """,
                relations=batch,
            )

        # 3. 批量创建 ON_PRODUCT 关系（Transaction → Product）
        for i in range(0, len(on_product_relations), batch_size):
            batch = on_product_relations[i:i+batch_size]
            await neo4j_session.run(
                """
                UNWIND $relations AS rel
                MATCH (t:Transaction {transaction_no: rel.tx_no}), (p:Product {id: rel.pid})
                MERGE (t)-[:ON_PRODUCT]->(p)
                """,
                relations=batch,
            )

    print(f"  [OK] Transaction 节点 ({len(tx_data)}) + MADE/ON_PRODUCT 关系（批量导入）")


async def import_employees(driver):
    """从 MySQL 导入员工数据，创建 Employee 节点 + MANAGES/HANDLED_BY 关系（批量导入优化）"""
    async with async_session_factory() as mysql_session:
        # 查询所有员工（sys_user 没有 department 列，用 employee_role 代替）
        emp_result = await mysql_session.execute(
            text("SELECT id, username, real_name, user_type, employee_role "
                 "FROM sys_user WHERE user_type = 'EMPLOYEE'")
        )
        employees = emp_result.fetchall()

        # 查询交易记录中的经办人（用于建立 HANDLED_BY 和 MANAGES 关系）
        tx_result = await mysql_session.execute(
            text("SELECT transaction_no, operator_id, customer_id "
                 "FROM fin_transaction WHERE operator_id IS NOT NULL AND operator_id > 0")
        )
        tx_records = tx_result.fetchall()

    # 收集员工数据
    employees_data = []
    handled_by_relations = []  # Transaction → Employee
    manages_relations = []     # Employee → Customer (去重)
    manages_set = set()        # 用于去重

    for row in employees:
        emp_id = row[0]
        username = row[1]
        real_name = row[2] or username
        employee_role = row[4] or ""

        employees_data.append({
            "employee_id": emp_id,
            "name": real_name,
            "username": username,
            "role": employee_role,
            "department": "",
        })

    # 从交易记录构建 HANDLED_BY 和 MANAGES 关系
    for row in tx_records:
        tx_no = row[0]
        operator_id = row[1]
        customer_id = row[2]

        # HANDLED_BY: Transaction → Employee
        handled_by_relations.append({"tx_no": tx_no, "emp_id": operator_id})

        # MANAGES: Employee → Customer (去重)
        manages_key = (operator_id, customer_id)
        if manages_key not in manages_set:
            manages_set.add(manages_key)
            manages_relations.append({"emp_id": operator_id, "cid": customer_id})

    # 批量执行 Neo4j 操作
    async with driver.session(database=settings.neo4j.database) as neo4j_session:
        # 1. 批量创建 Employee 节点
        if employees_data:
            await neo4j_session.run(
                """
                UNWIND $employees AS e
                MERGE (emp:Employee {employee_id: e.employee_id})
                SET emp.name = e.name, emp.username = e.username,
                    emp.role = e.role, emp.department = e.department
                """,
                employees=employees_data,
            )

        batch_size = 1000

        # 2. 批量创建 HANDLED_BY 关系（Transaction → Employee）
        for i in range(0, len(handled_by_relations), batch_size):
            batch = handled_by_relations[i:i+batch_size]
            await neo4j_session.run(
                """
                UNWIND $relations AS rel
                MATCH (t:Transaction {transaction_no: rel.tx_no}), (e:Employee {employee_id: rel.emp_id})
                MERGE (t)-[:HANDLED_BY]->(e)
                """,
                relations=batch,
            )

        # 3. 批量创建 MANAGES 关系（Employee → Customer）
        for i in range(0, len(manages_relations), batch_size):
            batch = manages_relations[i:i+batch_size]
            await neo4j_session.run(
                """
                UNWIND $relations AS rel
                MATCH (e:Employee {employee_id: rel.emp_id}), (c:Customer {id: rel.cid})
                MERGE (e)-[:MANAGES]->(c)
                """,
                relations=batch,
            )

    print(f"  [OK] Employee 节点 ({len(employees_data)}) + MANAGES({len(manages_relations)})/HANDLED_BY({len(handled_by_relations)}) 关系（批量导入）")


async def import_knowledge(driver):
    """从 MySQL 导入知识元数据，创建 Knowledge 节点（批量导入优化）
    注：DOCUMENTED_BY/REFERENCES 关系需要额外数据支持，暂不创建"""
    async with async_session_factory() as mysql_session:
        result = await mysql_session.execute(
            text("SELECT id, knowledge_type, title, source_file, minio_path, "
                 "milvus_collection, version, status, expire_at "
                 "FROM fin_knowledge_meta ORDER BY id ASC")
        )
        knowledge_rows = result.fetchall()

    # 收集知识节点数据
    knowledge_data = []
    for row in knowledge_rows:
        knowledge_data.append({
            "knowledge_id": f"K{row[0]:04d}",
            "title": row[2] or "",
            "knowledge_type": row[1] or "",
            "source_file": row[3] or "",
            "minio_path": row[4] or "",
            "milvus_collection": row[5] or "",
            "version": row[6] or "",
            "status": row[7] or "",
            "expire_at": str(row[8]) if row[8] else "",
        })

    # 批量执行 Neo4j 操作
    async with driver.session(database=settings.neo4j.database) as neo4j_session:
        # 批量创建 Knowledge 节点
        if knowledge_data:
            await neo4j_session.run(
                """
                UNWIND $knowledge AS k
                MERGE (kn:Knowledge {knowledge_id: k.knowledge_id})
                SET kn.title = k.title, kn.knowledge_type = k.knowledge_type,
                    kn.source_file = k.source_file, kn.minio_path = k.minio_path,
                    kn.milvus_collection = k.milvus_collection,
                    kn.version = k.version, kn.status = k.status,
                    kn.expire_at = k.expire_at
                """,
                knowledge=knowledge_data,
            )

    print(f"  [OK] Knowledge 节点 ({len(knowledge_data)})（批量导入，暂不创建关系）")


async def create_customer_relations(driver):
    """创建 Customer 间 RELATED_TO 关系（基于共同持仓）"""
    async with driver.session(database=settings.neo4j.database) as neo4j_session:
        # 基于共同持仓产品创建 RELATED_TO 关系
        # 两个客户持有相同产品 → 建立关联，strength = 共同产品数
        await neo4j_session.run(
            """
            MATCH (c1:Customer)-[:INVESTS_IN]->(p:Product)<-[:INVESTS_IN]-(c2:Customer)
            WHERE c1.id < c2.id  // 避免重复和自关联
            WITH c1, c2, COUNT(p) AS common_products,
                 COLLECT(p.name) AS product_names
            WHERE common_products >= 1
            MERGE (c1)-[r:RELATED_TO]->(c2)
            SET r.relation_type = '共同持仓',
                r.strength = common_products,
                r.detected_at = datetime(),
                r.product_names = product_names
            """
        )
        print("  [OK] RELATED_TO 关系（基于共同持仓，已创建）")


async def show_stats(driver):
    """打印导入后的图谱统计"""
    async with driver.session(database=settings.neo4j.database) as session:
        # 节点统计
        for label in ["Customer", "Product", "CustomerRiskLevel", "ProductRiskLevel",
                      "Industry", "FundManager", "Market", "Transaction", "Employee",
                      "Knowledge"]:
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
    """创建索引（幂等），加速后续 MERGE 和查询
    注：有唯一性约束的字段不在此创建索引（约束会自动创建索引，两者不能共存）"""
    index_statements = [
        # Product 非唯一索引（code 由约束管理）
        "CREATE INDEX IF NOT EXISTS FOR (n:Product) ON (n.type)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Product) ON (n.status)",
        # Industry
        "CREATE INDEX IF NOT EXISTS FOR (n:Industry) ON (n.name)",
        # Transaction 非唯一索引（transaction_no 由约束管理）
        "CREATE INDEX IF NOT EXISTS FOR (n:Transaction) ON (n.status)",
        # Employee
        "CREATE INDEX IF NOT EXISTS FOR (n:Employee) ON (n.role)",
        # Knowledge
        "CREATE INDEX IF NOT EXISTS FOR (n:Knowledge) ON (n.title)",
        # 关系属性查询加速
        "CREATE INDEX IF NOT EXISTS FOR ()-[r:INVESTS_IN]->() ON (r.shares)",
    ]
    async with driver.session(database=settings.neo4j.database) as session:
        for stmt in index_statements:
            await session.run(stmt)
    print(f"  [OK] 索引 ({len(index_statements)})")


async def create_constraints(driver):
    """创建唯一性约束（幂等，确保关键节点 ID 不重复）
    在数据导入完成后执行，约束会自动创建对应的索引
    先动态查找并删除冲突的旧索引"""
    # 约束定义：(节点标签, 属性名, 约束名)
    constraints_def = [
        ("Customer", "id", "customer_id_unique"),
        ("Product", "id", "product_id_unique"),
        ("Product", "code", "product_code_unique"),
        ("Employee", "employee_id", "employee_id_unique"),
        ("Transaction", "transaction_no", "transaction_no_unique"),
        ("Knowledge", "knowledge_id", "knowledge_id_unique"),
        ("CustomerRiskLevel", "level_code", "customer_risk_level_unique"),
        ("ProductRiskLevel", "level_code", "product_risk_level_unique"),
    ]

    async with driver.session(database=settings.neo4j.database) as session:
        # 1. 查找并删除会与约束冲突的索引
        result = await session.run(
            "SHOW INDEXES YIELD name, entityType, labelsOrTypes, properties, type "
            "WHERE type = 'RANGE' AND entityType = 'NODE'"
        )
        indexes = await result.data()

        for label, prop, _ in constraints_def:
            for idx in indexes:
                idx_labels = idx.get("labelsOrTypes") or []
                idx_props = idx.get("properties") or []
                if label in idx_labels and prop in idx_props:
                    try:
                        await session.run(f"DROP INDEX {idx['name']}")
                    except Exception:
                        pass  # 删除失败则忽略

        # 2. 创建唯一性约束
        success_count = 0
        for label, prop, cname in constraints_def:
            stmt = (
                f"CREATE CONSTRAINT {cname} IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
            )
            try:
                await session.run(stmt)
                success_count += 1
            except Exception as e:
                if "already exists" not in str(e).lower():
                    print(f"  [WARN] {cname} 创建失败: {e}")

    print(f"  [OK] 唯一性约束 ({success_count}/{len(constraints_def)})")


async def main():
    """主入口"""
    print("=" * 50)
    print("[DEPLOY] Neo4j 知识图谱数据导入")
    print("=" * 50)

    # 安全检查：必须传 --confirm 才执行清空操作
    if "--confirm" not in sys.argv:
        print("\n[WARN]  警告：此脚本将清空 Neo4j 数据库中的全部数据后重新导入。")
        print(f"   目标数据库: {settings.neo4j.database}")
        print("\n   如需继续，请添加 --confirm 参数：")
        print("   python -m scripts.neo4j_import --confirm")
        sys.exit(1)

    driver = get_neo4j_driver()

    try:
        # 先清空（开发阶段）
        print("\n[1/15] 清空旧数据...")
        async with driver.session(database=settings.neo4j.database) as session:
            await session.run("MATCH (n) DETACH DELETE n")
        print("  [OK] 已清空")

        # 创建索引（幂等，加速后续 MERGE 和查询）
        print("\n[2/15] 创建索引...")
        await create_indexes(driver)

        # 按顺序导入
        print("\n[3/15] 导入客户风险等级 (C1-C5)...")
        await import_customer_risk_levels(driver)

        print("\n[4/15] 导入产品风险等级 (R1-R5)...")
        await import_product_risk_levels(driver)

        print("\n[5/15] 导入 Mock 行业...")
        await import_mock_industries(driver)

        print("\n[6/15] 导入 Mock 基金经理...")
        await import_mock_managers(driver)

        print("\n[7/15] 导入 Mock 市场...")
        await import_mock_markets(driver)

        print("\n[8/15] 导入产品数据 (MySQL → Neo4j)...")
        await import_products(driver)

        print("\n[9/15] 导入客户数据 (MySQL → Neo4j)...")
        await import_customers(driver)

        print("\n[10/15] 导入持仓关系 (MySQL → Neo4j)...")
        await import_holdings(driver)

        print("\n[11/15] 导入交易流水 (MySQL → Neo4j)...")
        await import_transactions(driver)

        print("\n[12/15] 导入员工数据 (MySQL → Neo4j)...")
        await import_employees(driver)

        print("\n[13/15] 导入知识元数据 (MySQL → Neo4j)...")
        await import_knowledge(driver)

        print("\n[14/15] 创建 Customer 间关联关系...")
        await create_customer_relations(driver)

        print("\n[15/15] 创建唯一性约束...")
        await create_constraints(driver)

        # 统计
        print("\n图谱统计:")
        await show_stats(driver)

        print("\n" + "=" * 50)
        print("[OK] 导入完成！")
        print("=" * 50)
    finally:
        # 确保连接池被清理
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
