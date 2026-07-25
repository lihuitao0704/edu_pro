"""
清空所有用户数据并重新插入演示数据
确保"演示客户NN"的数据库ID就是NN

⚠️ 会删除所有用户数据，仅用于演示环境！
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.settings import get_settings


def truncate_all():
    import pymysql
    settings = get_settings()
    conn = pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=settings.mysql.password,
        database=settings.mysql.database,
        charset="utf8mb4",
    )
    tables = [
        "fin_risk_assessment",
        "fin_customer_profile",
        "fin_holdings",
        "fin_transaction",
        "fin_risk_alert",
        "biz_work_order",
        "sys_user",
    ]
    with conn.cursor() as cur:
        for table in tables:
            cur.execute(f"TRUNCATE TABLE {table}")
            print(f"  TRUNCATE {table}")
    conn.commit()
    conn.close()
    print("全部清空完成")


if __name__ == "__main__":
    print("=== Step 1: 清空所有数据 ===")
    truncate_all()
    print("\n=== Step 2: 重新插入演示数据 ===")
    from scripts.seed_demo_data import apply_dataset
    apply_dataset()
    print("\n=== Step 3: 验证ID映射 ===")
    import pymysql
    settings = get_settings()
    conn = pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=settings.mysql.password,
        database=settings.mysql.database,
        charset="utf8mb4",
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, username, real_name FROM sys_user "
            "WHERE username LIKE 'demo_customer_%' ORDER BY id LIMIT 10"
        )
        rows = cur.fetchall()
        print("演示客户ID映射验证:")
        for row in rows:
            print(f"  ID={row[0]:2d} | {row[1]:20s} | {row[2]}")
    conn.close()
    print("\n完成！")
