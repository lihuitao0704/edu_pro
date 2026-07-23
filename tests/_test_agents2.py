"""阶段2续：数据分析/风控/投顾/业务操作 测试"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import httpx

BASE = "http://127.0.0.1:8000"
c = httpx.Client(timeout=120)

def test(name, url, body):
    print(f"\n{'='*60}\n测试: {name}\n{'='*60}", flush=True)
    t0 = time.time()
    try:
        r = c.post(url, json=body)
        print(f"状态码: {r.status_code}  耗时: {time.time()-t0:.1f}s", flush=True)
        d = r.json()
        print(json.dumps(d, ensure_ascii=False, indent=2)[:2500], flush=True)
    except Exception as e:
        print(f"❌ 失败 ({time.time()-t0:.1f}s): {e}", flush=True)

# 2.3 数据分析（NL2SQL）
test("数据分析-客户AUM统计", f"{BASE}/api/chat/analyst",
     {"session_id": "e2e-an-101", "message": "AUM超过100万的客户有多少个", "user_id": 2})

# 2.4 风控监测（规则引擎，不依赖LLM，应秒回）
test("风控-大额现金交易预警", f"{BASE}/api/risk/monitor",
     {"customer_id": 5, "transaction_id": "TXN_E2E_001", "amount": 150000,
      "transaction_type": "cash", "timestamp": "2026-07-22T10:00:00"})

# 2.5 投顾助手（GraphRAG + 画像 + LLM Agent）
test("投顾-产品推荐", f"{BASE}/api/chat/advisor",
     {"session_id": "e2e-ad-001", "message": "给客户推荐3款稳健型产品", "customer_id": 3})

# 2.6 业务操作（NL2API + Function Calling）
test("业务操作-产品申购", f"{BASE}/api/chat/operator",
     {"message": "帮客户3申购1万元F000001产品", "session_id": "e2e-op-001",
      "user_id": 2, "user_role": "理财顾问"})

c.close()
print("\n\n阶段2续 测试完成。", flush=True)
