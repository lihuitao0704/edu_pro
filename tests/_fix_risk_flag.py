"""临时脚本：修复 fin_customer_profile 缺失的 risk_flag 字段"""
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
try:
    cur.execute("ALTER TABLE fin_customer_profile ADD COLUMN risk_flag VARCHAR(16) NULL COMMENT '风险标记: normal/warning/high'")
    conn.commit()
    print("risk_flag 字段添加成功")
except Exception as e:
    if "Duplicate column" in str(e) or "already exists" in str(e):
        print("risk_flag 字段已存在，无需修改")
    else:
        print(f"添加失败: {e}")
finally:
    cur.close()
    conn.close()
