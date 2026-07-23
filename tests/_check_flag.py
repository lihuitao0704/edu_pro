"""查询客户画像 risk_flag"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pymysql
from app.config.settings import get_settings
s = get_settings()
conn = pymysql.connect(host=s.mysql.host, port=s.mysql.port, user=s.mysql.user,
    password=s.mysql.password, database=s.mysql.database, charset="utf8mb4")
cur = conn.cursor()
cur.execute("SELECT customer_id, risk_level, risk_flag FROM fin_customer_profile")
for r in cur.fetchall():
    print(f"  customer_id={r[0]}, risk_level={r[1]}, risk_flag={r[2]}")
cur.close()
conn.close()
