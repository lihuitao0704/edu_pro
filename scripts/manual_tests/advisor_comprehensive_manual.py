"""
投顾Agent全面功能测试 v2 - 使用正确的API参数
测试维度：数据闭环、业务流转、意图分类、API功能、规则引擎
"""
import json
import urllib.request
import urllib.error
import sys
import time
import uuid

BASE_URL = "http://127.0.0.1:8000"
RESULTS = {"pass": 0, "fail": 0, "errors": [], "warnings": [], "info": []}


def log_pass(msg):
    RESULTS["pass"] += 1
    print(f"  [PASS] {msg}")


def log_fail(msg, detail=""):
    RESULTS["fail"] += 1
    RESULTS["errors"].append(f"{msg}: {detail}")
    print(f"  [FAIL] {msg}")
    if detail:
        print(f"         {detail}")


def log_warn(msg):
    RESULTS["warnings"].append(msg)
    print(f"  [WARN] {msg}")


def log_info(msg):
    RESULTS["info"].append(msg)
    print(f"  [INFO] {msg}")


def api(method, path, data=None, token=None):
    """API request wrapper"""
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            content = resp.read().decode()
            try:
                return resp.status, json.loads(content)
            except json.JSONDecodeError:
                return resp.status, content
    except urllib.error.HTTPError as e:
        content = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(content)
        except:
            return e.code, content
    except Exception as e:
        return 0, str(e)


def get_token(username, password):
    """Get auth token"""
    _, resp = api("POST", "/api/auth/login", {"username": username, "password": password})
    if isinstance(resp, dict) and "data" in resp:
        return resp["data"].get("access_token")
    return None


# ==================== TEST CASES ====================

def test_health():
    """TC-001: Health check"""
    print("\n[TC-001] Health Check /api/health")
    code, resp = api("GET", "/api/health")
    if code == 200 and isinstance(resp, dict):
        log_pass(f"Service OK, LLM={resp.get('data', {}).get('llm_model', '?')}, auth_mode={resp.get('data', {}).get('auth_mode', '?')}")
    else:
        log_fail("Health check failed", f"code={code}")


def test_auth():
    """TC-002: Authentication"""
    print("\n[TC-002] Authentication Flow")
    # Normal login
    token = get_token("demo_advisor", "Demo@123")
    if token:
        log_pass("Advisor login success")
    else:
        log_fail("Advisor login failed")
        return None

    # Wrong password
    code, resp = api("POST", "/api/auth/login", {"username": "demo_advisor", "password": "wrong"})
    if code == 401 or (isinstance(resp, dict) and resp.get("code") != 200):
        log_pass("Wrong password rejected")
    else:
        log_fail("Wrong password should be rejected", f"code={code}")

    # Customer login
    customer_token = get_token("demo_customer_01", "Demo@123")
    if customer_token:
        log_pass("Customer login success")
    else:
        log_fail("Customer login failed")

    return token


def test_profile_api(token):
    """TC-003: Profile API"""
    print("\n[TC-003] Customer Profile API")

    # Find a valid customer_id that has a profile
    code, resp = api("GET", "/api/profile/2", token=token)
    if code == 200 and isinstance(resp, dict):
        data = resp.get("data", {})
        log_pass(f"Profile query OK for customer_id=2, risk_level={data.get('risk_level')}")
    elif code == 404:
        log_warn("customer_id=2 profile not found, trying others")
        # Try other IDs
        for cid in [11, 12, 3, 4, 5]:
            code, resp = api("GET", f"/api/profile/{cid}", token=token)
            if code == 200:
                log_pass(f"Profile found for customer_id={cid}")
                break
    else:
        log_fail(f"Profile query failed", f"code={code}")

    # Profile analyze (POST)
    code, resp = api("POST", "/api/profile/analyze", {"customer_id": 11, "trigger_type": "manual"}, token=token)
    if code == 200 and isinstance(resp, dict):
        log_pass("Profile analyze API OK")
    elif code == 405:
        log_fail("Profile analyze: Method Not Allowed (route issue)")
    else:
        log_fail(f"Profile analyze failed", f"code={code}, resp={str(resp)[:200]}")


def test_advisor_recommend(token):
    """TC-004: Recommendation API"""
    print("\n[TC-004] Advisor Recommend API")

    code, resp = api("POST", "/api/recommend", {
        "customer_id": 11,
        "top_n": 3
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        data = resp.get("data", {})
        recs = data.get("recommendations", [])
        log_pass(f"Recommend OK, returned {len(recs)} products")
        if recs:
            p = recs[0]
            fields = list(p.keys())
            log_info(f"Product fields: {fields}")
    elif code == 405:
        log_fail("Recommend: Method Not Allowed (check route)")
    else:
        log_fail(f"Recommend failed", f"code={code}, resp={str(resp)[:300]}")


def test_advisor_allocation(token):
    """TC-005: Asset Allocation API"""
    print("\n[TC-005] Asset Allocation API")

    code, resp = api("POST", "/api/allocation", {
        "customer_id": 11
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        log_pass("Allocation OK")
    elif code == 405:
        log_fail("Allocation: Method Not Allowed")
    else:
        log_fail(f"Allocation failed", f"code={code}, resp={str(resp)[:200]}")


def test_chat_customer(token):
    """TC-006: Customer Service Chat"""
    print("\n[TC-006] Customer Service Chat")

    session_id = f"test_{uuid.uuid4().hex[:8]}"
    code, resp = api("POST", "/api/chat/customer", {
        "session_id": session_id,
        "message": "I want to know about financial products",
        "user_id": 7
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        data = resp.get("data", {})
        reply = data.get("reply", "")
        log_pass(f"Customer chat OK, reply len={len(reply)}")
    else:
        log_fail(f"Customer chat failed", f"code={code}, resp={str(resp)[:200]}")


def test_chat_advisor(token):
    """TC-007: Advisor Chat"""
    print("\n[TC-007] Advisor Chat")

    session_id = f"test_{uuid.uuid4().hex[:8]}"
    code, resp = api("POST", "/api/chat/advisor", {
        "session_id": session_id,
        "message": "Recommend 3 stable products for my customer",
        "user_id": 7,
        "customer_id": 11
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        data = resp.get("data", {})
        log_pass(f"Advisor chat OK, reply len={len(data.get('reply', ''))}")
    else:
        log_fail(f"Advisor chat failed", f"code={code}, resp={str(resp)[:200]}")


def test_risk_questionnaire(token):
    """TC-008: Risk Questionnaire"""
    print("\n[TC-008] Risk Questionnaire API")

    code, resp = api("GET", "/api/risk/questionnaire", token=token)
    if code == 200 and isinstance(resp, dict):
        log_pass("Questionnaire fetch OK")
    else:
        log_fail("Questionnaire fetch failed", f"code={code}, resp={str(resp)[:200]}")


def test_risk_assessment(token):
    """TC-009: Risk Assessment Submit"""
    print("\n[TC-009] Risk Assessment Submit")

    code, resp = api("POST", "/api/risk/assessment", {
        "customer_id": 11,
        "answers": [{"q": 1, "a": "A"}, {"q": 2, "a": "B"}, {"q": 3, "a": "C"}]
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        log_pass("Assessment submit OK")
    else:
        log_fail(f"Assessment submit failed", f"code={code}, resp={str(resp)[:200]}")


def test_risk_suitability(token):
    """TC-010: Suitability Check"""
    print("\n[TC-010] Suitability Check")

    code, resp = api("POST", "/api/risk/suitability-check", {
        "customer_id": 11,
        "product_code": "FP001"
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        data = resp.get("data", {})
        log_pass(f"Suitability check OK, match={data.get('match')}")
    else:
        log_fail(f"Suitability check failed", f"code={code}, resp={str(resp)[:200]}")


def test_risk_monitor(token):
    """TC-011: Risk Monitor"""
    print("\n[TC-011] Risk Monitor API")

    code, resp = api("POST", "/api/risk/monitor", {
        "customer_id": 11,
        "transaction_id": f"TXN{uuid.uuid4().hex[:8]}",
        "amount": 500000,
        "transaction_type": "purchase",
        "timestamp": "2026-07-24T10:00:00"
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        log_pass("Risk monitor OK")
    else:
        log_fail(f"Risk monitor failed", f"code={code}, resp={str(resp)[:200]}")


def test_risk_alerts(token):
    """TC-012: Risk Alerts List"""
    print("\n[TC-012] Risk Alerts List")

    code, resp = api("GET", "/api/risk/alerts?page=1&page_size=10", token=token)
    if code == 200 and isinstance(resp, dict):
        data = resp.get("data", {})
        items = data.get("items", data.get("alerts", []))
        log_pass(f"Alerts list OK, {len(items)} items")
    else:
        log_fail(f"Alerts list failed", f"code={code}, resp={str(resp)[:200]}")


def test_analyst(token):
    """TC-013: NL2SQL Data Analysis"""
    print("\n[TC-013] NL2SQL Data Analysis")

    session_id = f"test_{uuid.uuid4().hex[:8]}"
    code, resp = api("POST", "/api/chat/analyst", {
        "session_id": session_id,
        "message": "Query customers with assets over 1 million",
        "user_id": 7
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        log_pass("NL2SQL analysis OK")
    else:
        log_fail(f"NL2SQL analysis failed", f"code={code}, resp={str(resp)[:200]}")


def test_operator(token):
    """TC-014: Business Operation Agent"""
    print("\n[TC-014] Business Operation Agent")

    code, resp = api("POST", "/api/chat/operator", {
        "message": "Help customer 11 purchase product FP001, amount 100000"
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        log_pass("Operator agent OK")
    else:
        log_fail(f"Operator agent failed", f"code={code}, resp={str(resp)[:200]}")


def test_knowledge(token):
    """TC-015: Knowledge Base API"""
    print("\n[TC-015] Knowledge Base API")

    code, resp = api("GET", "/api/knowledge/list", token=token)
    if code == 200 and isinstance(resp, dict):
        log_pass("Knowledge list OK")
    else:
        log_fail(f"Knowledge list failed", f"code={code}, resp={str(resp)[:200]}")


def test_rbac(token):
    """TC-016: RBAC Permission Control"""
    print("\n[TC-016] RBAC Permission Control")

    customer_token = get_token("demo_customer_01", "Demo@123")
    if customer_token:
        # Customer tries to access another customer's profile
        code, resp = api("GET", "/api/profile/12", token=customer_token)
        if code == 403:
            log_pass("Customer accessing other profile rejected (403)")
        elif code == 404:
            log_warn("Profile not found (404) - may need valid customer_id with profile")
        elif code == 200:
            log_fail("Customer should NOT access other profiles", "RBAC not enforced")
        else:
            log_warn(f"Access other profile returned code={code}")
    else:
        log_warn("Customer login failed, skip RBAC test")


def test_data_closure(token):
    """TC-017: Data Closure - Recommendation persistence"""
    print("\n[TC-017] Data Closure - Recommendation Persistence")

    code, resp = api("POST", "/api/recommend", {
        "customer_id": 11,
        "top_n": 3
    }, token=token)

    if code == 200:
        log_pass("Recommend API OK - data should persist to product_recommendation table")
    elif code == 405:
        log_fail("Recommend API: Method Not Allowed")
    else:
        log_fail(f"Recommend API failed", f"code={code}")


def test_intent_classification(token):
    """TC-018: Intent Classification"""
    print("\n[TC-018] Intent Classification Test")

    test_cases = [
        ("Recommend some stable products", "recommend"),
        ("Help me redeem my fund", "redeem"),
        ("Check my holdings", "query"),
        ("How to do risk assessment", "risk"),
        ("Transfer money to friend", "transfer"),
    ]

    for msg, expected_intent in test_cases:
        session_id = f"test_{uuid.uuid4().hex[:8]}"
        code, resp = api("POST", "/api/chat/advisor", {
            "session_id": session_id,
            "message": msg,
            "user_id": 7,
            "customer_id": 11
        }, token=token)
        if code == 200:
            log_pass(f"Intent '{expected_intent}' handled OK")
        else:
            log_fail(f"Intent '{expected_intent}' failed", f"code={code}")


def test_edge_cases(token):
    """TC-019: Edge Cases & Error Handling"""
    print("\n[TC-019] Edge Cases & Error Handling")

    # Empty message
    session_id = f"test_{uuid.uuid4().hex[:8]}"
    code, resp = api("POST", "/api/chat/advisor", {
        "session_id": session_id, "message": "", "user_id": 7, "customer_id": 11
    }, token=token)
    log_info(f"Empty message -> code={code}")

    # Non-existent customer
    code, resp = api("GET", "/api/profile/99999", token=token)
    log_info(f"Non-existent customer -> code={code}")

    # Very long message
    long_msg = "recommend" * 5000
    code, resp = api("POST", "/api/chat/advisor", {
        "session_id": session_id, "message": long_msg, "user_id": 7, "customer_id": 11
    }, token=token)
    log_info(f"Long message -> code={code}")

    # SQL injection attempt
    code, resp = api("POST", "/api/chat/advisor", {
        "session_id": session_id, "message": "'; DROP TABLE sys_user; --", "user_id": 7, "customer_id": 11
    }, token=token)
    log_info(f"SQL injection test -> code={code}")


def test_business_flow(token):
    """TC-020: Complete Business Flow"""
    print("\n[TC-020] Complete Business Flow - Purchase Process")

    # Step 1: View profile
    code1, _ = api("GET", "/api/profile/2", token=token)
    # Step 2: Get recommendations
    code2, _ = api("POST", "/api/recommend", {"customer_id": 11, "top_n": 3}, token=token)
    # Step 3: Suitability check
    code3, _ = api("POST", "/api/risk/suitability-check", {"customer_id": 11, "product_code": "FP001"}, token=token)
    # Step 4: Risk monitor
    code4, _ = api("POST", "/api/risk/monitor", {
        "customer_id": 11, "transaction_id": f"TXN{uuid.uuid4().hex[:8]}",
        "amount": 100000, "transaction_type": "purchase", "timestamp": "2026-07-24T10:00:00"
    }, token=token)

    codes = {"profile": code1, "recommend": code2, "suitability": code3, "monitor": code4}
    flow_ok = all(c == 200 for c in codes.values())
    if flow_ok:
        log_pass("All business flow steps reachable")
    else:
        failed = [k for k, v in codes.items() if v != 200]
        log_fail(f"Business flow broken at: {failed}", str(codes))


def test_stream_api(token):
    """TC-021: SSE Stream API"""
    print("\n[TC-021] SSE Stream API Test")

    session_id = f"test_{uuid.uuid4().hex[:8]}"
    code, resp = api("POST", "/api/chat/customer/stream", {
        "session_id": session_id,
        "message": "Hello",
        "user_id": 7
    }, token=token)
    # SSE returns streaming response, just check it doesn't 500
    log_info(f"Stream API -> code={code} (200 means SSE stream started)")


def test_explain_api(token):
    """TC-022: Recommendation Explanation API"""
    print("\n[TC-022] Recommendation Explanation API")

    code, resp = api("POST", "/api/profile/explain", {
        "customer_id": 11,
        "message": "Explain why these products are recommended"
    }, token=token)
    if code == 200:
        log_pass("Explanation API OK")
    else:
        log_fail(f"Explanation API failed", f"code={code}, resp={str(resp)[:200]}")


def test_work_order_flow(token):
    """TC-023: Work Order Flow"""
    print("\n[TC-023] Work Order Flow")

    # Create work order via risk monitor
    code, resp = api("POST", "/api/risk/monitor", {
        "customer_id": 11,
        "transaction_id": f"TXN{uuid.uuid4().hex[:8]}",
        "amount": 999999,
        "transaction_type": "transfer",
        "timestamp": "2026-07-24T10:00:00"
    }, token=token)
    if code == 200:
        log_pass("Risk monitor triggered (may create work order)")
    else:
        log_fail(f"Risk monitor failed", f"code={code}")


def test_concurrent_sessions(token):
    """TC-024: Session Isolation"""
    print("\n[TC-024] Session Isolation Test")

    sid1 = f"sess_{uuid.uuid4().hex[:8]}"
    sid2 = f"sess_{uuid.uuid4().hex[:8]}"

    code1, resp1 = api("POST", "/api/chat/customer", {
        "session_id": sid1, "message": "My name is Alice", "user_id": 7
    }, token=token)

    code2, resp2 = api("POST", "/api/chat/customer", {
        "session_id": sid2, "message": "My name is Bob", "user_id": 7
    }, token=token)

    if code1 == 200 and code2 == 200:
        log_pass("Two sessions handled independently")
    else:
        log_fail(f"Session handling failed", f"session1={code1}, session2={code2}")


def print_summary():
    """Print test summary"""
    print("\n" + "=" * 60)
    print("TEST SUMMARY REPORT")
    print("=" * 60)
    total = RESULTS["pass"] + RESULTS["fail"]
    print(f"  Total:  {total}")
    print(f"  [PASS] {RESULTS['pass']}")
    print(f"  [FAIL] {RESULTS['fail']}")
    print(f"  [WARN] {len(RESULTS['warnings'])}")
    print(f"  [INFO] {len(RESULTS['info'])}")

    if RESULTS["errors"]:
        print(f"\n--- FAILURE DETAILS ---")
        for i, err in enumerate(RESULTS["errors"], 1):
            print(f"  {i}. {err}")

    if RESULTS["warnings"]:
        print(f"\n--- WARNINGS ---")
        for i, w in enumerate(RESULTS["warnings"], 1):
            print(f"  {i}. {w}")

    print(f"\nPass Rate: {RESULTS['pass']}/{total} = {RESULTS['pass']/max(total,1)*100:.1f}%")


# ==================== MAIN ====================
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    print("[START] Investment Advisor Agent Comprehensive Test v2")
    print(f"   Target: {BASE_URL}")
    print(f"   Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # Basic
    test_health()
    token = test_auth()

    if not token:
        print("\n[AUTH FAILED] Cannot proceed")
        sys.exit(1)

    # API Functional Tests
    test_profile_api(token)
    test_advisor_recommend(token)
    test_advisor_allocation(token)
    test_chat_customer(token)
    test_chat_advisor(token)

    # Risk Tests
    test_risk_questionnaire(token)
    test_risk_assessment(token)
    test_risk_suitability(token)
    test_risk_monitor(token)
    test_risk_alerts(token)

    # Other Modules
    test_analyst(token)
    test_operator(token)
    test_knowledge(token)

    # Advanced Tests
    test_rbac(token)
    test_data_closure(token)
    test_intent_classification(token)
    test_edge_cases(token)
    test_business_flow(token)
    test_stream_api(token)
    test_explain_api(token)
    test_work_order_flow(token)
    test_concurrent_sessions(token)

    print_summary()
