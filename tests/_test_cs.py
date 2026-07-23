"""单请求测试：智能客服"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import httpx

BASE = "http://127.0.0.1:8000"
print("测试智能客服...", flush=True)
t0 = time.time()
try:
    r = httpx.post(f"{BASE}/api/chat/customer",
                   json={"session_id": "e2e-cs-001", "message": "有什么稳健型理财", "user_id": 3},
                   timeout=90)
    print(f"状态码: {r.status_code}  耗时: {time.time()-t0:.1f}s", flush=True)
    data = r.json()
    print(json.dumps(data, ensure_ascii=False, indent=2)[:3000], flush=True)
except Exception as e:
    print(f"失败 ({time.time()-t0:.1f}s): {e}", flush=True)
