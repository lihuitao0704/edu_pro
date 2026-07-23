"""阶段3验证：风控预警 → 事件总线 → 画像 risk_flag 更新（协作闭环）"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import httpx, pymysql
from app.config.settings import get_settings
s = get_settings()

# 1. 发风控预警请求
print("=" * 55)
print("步骤1: 发送风控监测请求（客户5，大额现金15万）")
print("=" * 55)
r = httpx.post("http://127.0.0.1:8000/api/risk/monitor",
    json={"customer_id": 5, "transaction_id": "TXN_E2E_003", "amount": 150000,
          "transaction_type": "cash", "timestamp": "2026-07-22T10:00:00"},
    timeout=30)
print(f"状态码: {r.status_code}")
d = r.json()
print(f"预警级别: {d['data']['alert']['alert_level']}")
print(f"触发规则: {d['data']['alert']['trigger_rules']}")
print(f"置信度: {d['data']['alert']['confidence']}")

# 2. 等待事件消费（异步：发布→订阅→更新画像）
print("\n步骤2: 等待3秒让事件总线消费...")
time.sleep(3)

# 3. 查更新后的 risk_flag
print("\n步骤3: 查询客户5的 risk_flag（应从 None → warning）")
conn = pymysql.connect(host=s.mysql.host, port=s.mysql.port, user=s.mysql.user,
    password=s.mysql.password, database=s.mysql.database, charset="utf8mb4")
cur = conn.cursor()
cur.execute("SELECT customer_id, risk_level, risk_flag FROM fin_customer_profile")
rows = cur.fetchall()
for row in rows:
    marker = "  ← 已更新!" if (row[0] == 5 and row[2] is not None) else ""
    print(f"  customer_id={row[0]}, risk_level={row[1]}, risk_flag={row[2]}{marker}")
cur.close()
conn.close()

# 4. 结论
flag = [r[2] for r in rows if r[0] == 5][0]
print("\n" + "=" * 55)
if flag is not None:
    print(f"✅ 协作闭环验证成功！客户5 risk_flag: None → {flag}")
    print("   风控Agent → 事件总线 → 投顾画像更新 链路打通！")
else:
    print("❌ risk_flag 未更新，事件订阅可能未启动或消费失败")
print("=" * 55)
