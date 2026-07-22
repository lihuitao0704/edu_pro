"""
数据库表结构 vs ORM 模型 一致性检查脚本
用法: python scripts/check_db_schema.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql
from sqlalchemy import inspect
from app.config.settings import get_settings
from app.config.database import engine, Base
from app.model.entities import (
    SysUser, FinCustomerProfile, CustomerTag, RiskScoreRecord,
    RiskAssessment, RiskRule, ProductRecommendation,
)

settings = get_settings()

# ── 1. 连接 MySQL 获取真实表结构 ──────────────────────────
try:
    conn = pymysql.connect(
        host=settings.mysql.host, port=settings.mysql.port,
        user=settings.mysql.user, password=settings.mysql.password,
        database=settings.mysql.database, charset="utf8mb4",
    )
    cur = conn.cursor()
    print(f"✓ 已连接 MySQL: {settings.mysql.host}:{settings.mysql.port}/{settings.mysql.database}\n")
except Exception as e:
    print(f"✗ 无法连接数据库: {e}")
    print("  请检查 .env 中的 MYSQL_* 配置是否正确")
    sys.exit(1)

# ── 2. 获取所有 ORM 表 ────────────────────────────────────
orm_tables = {
    "sys_user":              SysUser,
    "fin_customer_profile":  FinCustomerProfile,
    "customer_tag":          CustomerTag,
    "risk_score_record":     RiskScoreRecord,
    "fin_risk_assessment":   RiskAssessment,
    "risk_rule":             RiskRule,
    "product_recommendation": ProductRecommendation,
}

# ── 3. 逐表比对 ──────────────────────────────────────────
for table_name, model_class in orm_tables.items():
    # 获取真实表结构
    cur.execute(f"DESCRIBE `{table_name}`")
    db_cols = {}
    for row in cur.fetchall():
        col_name = row[0]
        col_type = row[1].decode() if isinstance(row[1], bytes) else row[1]
        col_null = row[2]
        col_key  = row[3]
        col_default = row[4]
        db_cols[col_name] = {
            "type": col_type, "null": col_null, "key": col_key, "default": col_default,
        }

    # 获取 ORM 列定义
    mapper = inspect(model_class)
    orm_cols = {}
    for col in mapper.columns:
        orm_cols[col.name] = {
            "type": str(col.type),
            "nullable": col.nullable,
            "primary_key": col.primary_key,
        }

    # ── 比对 ──
    orm_only = set(orm_cols.keys()) - set(db_cols.keys())
    db_only  = set(db_cols.keys()) - set(orm_cols.keys())
    common   = set(orm_cols.keys()) & set(db_cols.keys())

    print(f"{'='*60}")
    print(f"表: {table_name}")
    print(f"{'='*60}")

    if orm_only:
        print(f"  ❌ ORM 中有但数据库缺失的字段: {orm_only}")
    if db_only:
        print(f"  ⚠️  数据库中有但 ORM 缺失的字段: {db_only}")
    if not orm_only and not db_only:
        print(f"  ✅ 字段数量一致 ({len(common)} 个)")

    # 类型比对
    type_mismatches = []
    for col_name in sorted(common):
        db = db_cols[col_name]
        orm = orm_cols[col_name]
        # 将 ORM 类型映射为 MySQL 期望类型
        orm_type_lower = orm["type"].lower()

        # 粗略类型兼容检查
        issues = []
        if "varchar" in orm_type_lower and "varchar" not in db["type"].lower():
            issues.append(f"ORM=VARCHAR ↔ DB={db['type']}")
        if "integer" in orm_type_lower or "bigint" in orm_type_lower:
            if not any(t in db["type"].lower() for t in ["int", "bigint", "tinyint"]):
                issues.append(f"ORM=INTEGER ↔ DB={db['type']}")
        if "decimal" in orm_type_lower or "numeric" in orm_type_lower:
            if not any(t in db["type"].lower() for t in ["decimal", "numeric", "double", "float"]):
                issues.append(f"ORM=DECIMAL ↔ DB={db['type']}")
        if "json" in orm_type_lower and "json" not in db["type"].lower():
            issues.append(f"ORM=JSON ↔ DB={db['type']}")
        if "datetime" in orm_type_lower:
            if not any(t in db["type"].lower() for t in ["datetime", "timestamp"]):
                issues.append(f"ORM=DATETIME ↔ DB={db['type']}")
        if "date" in orm_type_lower and "date" not in db["type"].lower():
            issues.append(f"ORM=DATE ↔ DB={db['type']}")
        if "text" in orm_type_lower and "text" not in db["type"].lower():
            issues.append(f"ORM=TEXT ↔ DB={db['type']}")

        # NULL 约束检查
        if orm["nullable"] == False and db["null"] == "YES":
            issues.append(f"ORM=NOT NULL ↔ DB=NULLABLE")

        if issues:
            type_mismatches.append((col_name, issues))

    if type_mismatches:
        print(f"  ❌ 类型/约束不一致 ({len(type_mismatches)} 个):")
        for col_name, issues in type_mismatches:
            for iss in issues:
                print(f"     {col_name}: {iss}")
    else:
        print(f"  ✅ 字段类型全部兼容")

    print()

cur.close()
conn.close()
print("检查完成。")
