"""
风控 Agent 答辩演示 — 10 个测试场景
===================================
运行: python tests/demo_10_scenarios.py
要求: 先启动 main.py（服务在 localhost:8000）
"""

import requests

BASE = "http://localhost:8000/api/risk"

SCENARIOS = [
    # (序号, 场景名, 交易数据, 预期结果)
    (1, "正常小额申购", {
        "customer_id": 1, "transaction_id": "TXN001", "amount": 10000,
        "transaction_type": "purchase", "timestamp": "2026-07-23T10:00:00" },
     "无预警 — 正常交易不触发任何规则"),

    (2, "大额现金交易", {
        "customer_id": 5, "transaction_id": "TXN002", "amount": 150000,
        "transaction_type": "cash", "timestamp": "2026-07-23T10:00:00" },
     "蓝色预警 · R001触发 — 单笔现金>=5万"),

    (3, "老年客户异常大额", {
        "customer_id": 3, "transaction_id": "TXN003", "amount": 120000,
        "transaction_type": "transfer", "timestamp": "2026-07-23T10:00:00" },
     "中高预警 · R016触发 — 65岁+12万>月均3倍"),

    (4, "金额与身份不符", {
        "customer_id": 1, "transaction_id": "TXN004", "amount": 550000, "daily_amount": 550000,
        "annual_income": 150000, "transaction_type": "transfer", "timestamp": "2026-07-23T10:00:00" },
     "中高预警 · R006触发 — 单日55万>年收入15万×3"),

    (5, "高风险国家交易", {
        "customer_id": 5, "transaction_id": "TXN005", "amount": 50000,
        "counterparty": {"country": "伊朗"}, "transaction_type": "transfer", "timestamp": "2026-07-23T10:00:00" },
     "红色预警 · R011触发 — FATF名单国家+>=1万"),

    (6, "整数规避特征", {
        "customer_id": 5, "transaction_id": "TXN006", "amount": 49999,
        "avoid_pattern_count": 6, "transaction_type": "transfer", "timestamp": "2026-07-23T10:00:00" },
     "中高预警 · R009触发 — 30天>=5笔规避金额"),

    (7, "资金快进快出", {
        "customer_id": 4, "transaction_id": "TXN007", "amount": 80000, "in_24h": True,
        "out_ratio": 0.95, "transaction_type": "transfer", "timestamp": "2026-07-23T10:00:00" },
     "中高预警 · R003触发 — 入账24h内95%转出"),

    (8, "涉赌涉诈特征", {
        "customer_id": 5, "transaction_id": "TXN008", "amount": 100000,
        "small_in_pattern": True, "large_round_out": True, "night_pattern": True,
        "transaction_type": "transfer", "timestamp": "2026-07-23T02:00:00" },
     "红色预警 · R019触发 — 小额入+大额整数出+夜间"),

    (9, "新开户短期大额", {
        "customer_id": 6, "transaction_id": "TXN009", "amount": 300000,
        "account_age_days": 15, "transaction_type": "transfer", "timestamp": "2026-07-23T10:00:00" },
     "中高预警 · R017触发 — 开户15天+单笔30万"),

    (10, "多规则同时触发", {
        "customer_id": 5, "transaction_id": "TXN010", "amount": 150000,
        "transaction_type": "cash", "night_pattern": True,
        "small_in_pattern": True, "large_round_out": True,
        "avoid_pattern_count": 6, "timestamp": "2026-07-23T02:00:00" },
     "黄色预警 — R001+R009+R019同时触发"),
]

print("=" * 70)
print("  风控Agent 答辩演示 — 10 个测试场景")
print("=" * 70)

for seq, name, tx, expected in SCENARIOS:
    print(f"\n{'─' * 50}")
    print(f"  {seq}. {name}")
    print(f"  {tx['transaction_id']} | 客户{tx['customer_id']} | 金额{tx['amount']:,} | {tx['transaction_type']}")

    try:
        resp = requests.post(f"{BASE}/monitor", json=tx, timeout=10)
        data = resp.json()

        if data["code"] != 200:
            print(f"  ❌ 请求失败: {data}")
            continue

        alert = data["data"]["alert"]
        count = data["data"]["triggered_count"]

        if alert is None:
            print(f"  结果: ✅ 无预警")
        else:
            rules = [r["rule_id"] for r in alert.get("trigger_rules", [])]
            print(f"  结果: 触发{count}条 | 等级={alert['alert_level']} | 规则={rules} | 置信度={alert.get('confidence',0)}")

        print(f"  预期: {expected}")
        print(f"  {'✅ 有预警' if alert else '⚠️ 无预警'}")

    except requests.ConnectionError:
        print("  ❌ 连接失败! 请先启动 main.py")
        break
    except Exception as e:
        print(f"  ❌ 错误: {e}")

print(f"\n{'=' * 70}")
print("  演示完成！打开 http://localhost:8000/docs 查看历史预警")
print("=" * 70)
