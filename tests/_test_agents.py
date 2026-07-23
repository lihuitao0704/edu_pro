"""阶段2：单 Agent 逐个跑通测试"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import httpx

BASE = "http://127.0.0.1:8000"
client = httpx.Client(timeout=120)


def test(name, method, url, body=None):
    print(f"\n{'='*60}")
    print(f"测试: {name}")
    print(f"请求: {method} {url}")
    if body:
        print(f"参数: {json.dumps(body, ensure_ascii=False)}")
    print(f"{'='*60}")
    try:
        t0 = time.time()
        if method == "POST":
            r = client.post(url, json=body)
        else:
            r = client.get(url)
        elapsed = time.time() - t0
        print(f"状态码: {r.status_code}  耗时: {elapsed:.2f}s")
        try:
            data = r.json()
            # 截断过长的 reply
            print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
        except Exception:
            print(r.text[:2000])
    except Exception as e:
        print(f"❌ 请求失败: {e}")


# ── 2.2 智能客服 Agent（RAG 链路）──
test("智能客服-产品咨询", "POST", f"{BASE}/api/chat/customer",
     {"session_id": "e2e-cs-001", "message": "有什么年化5%以上的稳健型理财？", "user_id": 3})

test("智能客服-多轮上下文", "POST", f"{BASE}/api/chat/customer",
     {"session_id": "e2e-cs-001", "message": "风险高吗", "user_id": 3})

# ── 2.3 数据分析 Agent（NL2SQL 链路）──
test("数据分析-客户统计", "POST", f"{BASE}/api/chat/analyst",
     {"session_id": "e2e-an-001", "message": "AUM超过100万的客户有多少个？", "user_id": 2})

test("数据分析-产品统计", "POST", f"{BASE}/api/chat/analyst",
     {"session_id": "e2e-an-002", "message": "各产品类型的平均收益率是多少？", "user_id": 2})

client.close()
print("\n\n阶段2 部分测试完成。")
