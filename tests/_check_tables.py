"""临时脚本：检查数据库所有表及行数"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pymysql
from app.config.settings import get_settings

s = get_settings()
conn = pymysql.connect(
    host=s.mysql.host, port=s.mysql.port, user=s.mysql.user,
    password=s.mysql.password, database=s.mysql.database, charset="utf8mb4",
)
cur = conn.cursor()
cur.execute("SHOW TABLES")
tables = [r[0] for r in cur.fetchall()]
print(f"数据库 {s.mysql.database} 共 {len(tables)} 张表:\n")
print(f"{'表名':<30} {'行数':>8}")
print("-" * 40)
for t in tables:
    try:
        cur.execute(f"SELECT COUNT(*) FROM `{t}`")
        cnt = cur.fetchone()[0]
        print(f"{t:<30} {cnt:>8}")
    except Exception as e:
        print(f"{t:<30} ERROR: {e}")

# 重点检查是否有 Mock 数据
print("\n=== 关键表数据抽样 ===")
for t, sql in [
    ("sys_user", "SELECT id, username, user_type, employee_role FROM sys_user LIMIT 5"),
    ("fin_product", "SELECT product_code, product_type, risk_level, status FROM fin_product LIMIT 5"),
    ("fin_holdings", "SELECT customer_id, product_id, shares FROM fin_holdings LIMIT 3"),
    ("fin_transaction", "SELECT customer_id, amount, transaction_type FROM fin_transaction LIMIT 3"),
]:
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        print(f"\n[{t}] {len(rows)} 行抽样:")
        for r in rows:
            print(f"  {r}")
    except Exception as e:
        print(f"\n[{t}] 查询失败: {e}")

cur.close()
conn.close()
