"""投顾 Agent 重测（补 user_id）"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import httpx

BASE = "http://127.0.0.1:8000"
c = httpx.Client(timeout=120)

print("测试投顾-产品推荐（补user_id）...", flush=True)
t0 = time.time()
try:
    r = c.post(f"{BASE}/api/chat/advisor",
               json={"session_id": "e2e-ad-002", "message": "给客户推荐3款稳健型产品",
                     "customer_id": 3, "user_id": 2})
    print(f"状态码: {r.status_code}  耗时: {time.time()-t0:.1f}s", flush=True)
    d = r.json()
    print(json.dumps(d, ensure_ascii=False, indent=2)[:3500], flush=True)
except Exception as e:
    print(f"❌ 失败 ({time.time()-t0:.1f}s): {e}", flush=True)
c.close()
print("\n投顾测试完成。", flush=True)
