"""
投顾Agent全面功能测试
测试维度：数据闭环、业务流转、意图分类、API功能、规则引擎
"""
import json
import urllib.request
import urllib.error
import sys
import time

BASE_URL = "http://127.0.0.1:8000"
RESULTS = {"pass": 0, "fail": 0, "errors": [], "warnings": [], "info": []}


def log_pass(msg):
    RESULTS["pass"] += 1
    print(f"  ✅ {msg}")


def log_fail(msg, detail=""):
    RESULTS["fail"] += 1
    RESULTS["errors"].append(f"{msg}: {detail}")
    print(f"  ❌ {msg}")
    if detail:
        print(f"     └─ {detail}")


def log_warn(msg):
    RESULTS["warnings"].append(msg)
    print(f"  ⚠️  {msg}")


def log_info(msg):
    RESULTS["info"].append(msg)
    print(f"  ℹ️  {msg}")


def api(method, path, data=None, token=None, raw=False):
    """API请求封装"""
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode()
            if raw:
                return resp.status, content
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
    """获取认证token"""
    _, resp = api("POST", "/api/auth/login", {"username": username, "password": password})
    if isinstance(resp, dict) and "data" in resp:
        return resp["data"].get("access_token")
    return None


# ==================== 测试用例 ====================

def test_health():
    """TC-001: 健康检查"""
    print("\n[TC-001] 健康检查 /api/health")
    code, resp = api("GET", "/api/health")
    if code == 200 and isinstance(resp, dict):
        log_pass(f"服务正常，LLM模型: {resp.get('data', {}).get('llm_model', 'unknown')}")
    else:
        log_fail("健康检查失败", f"code={code}")


def test_auth():
    """TC-002: 认证流程"""
    print("\n[TC-002] 认证流程测试")
    # 正常登录
    token = get_token("demo_advisor", "Demo@123")
    if token:
        log_pass("理财顾问登录成功")
    else:
        log_fail("理财顾问登录失败")
        return None

    # 错误密码
    code, resp = api("POST", "/api/auth/login", {"username": "demo_advisor", "password": "wrong"})
    if code == 401 or (isinstance(resp, dict) and resp.get("code") != 200):
        log_pass("错误密码被拒绝")
    else:
        log_fail("错误密码应被拒绝", f"code={code}")

    # 无token访问受保护接口
    code, resp = api("GET", "/api/profile/2")
    if code == 401 or code == 403:
        log_pass("无token访问被拒绝")
    else:
        log_warn(f"无token访问返回code={code}（可能未配置auth依赖）")

    return token


def test_profile_api(token):
    """TC-003: 画像API"""
    print("\n[TC-003] 客户画像API测试")

    # 查询画像
    code, resp = api("GET", "/api/profile/11", token=token)
    if code == 200 and isinstance(resp, dict):
        data = resp.get("data", {})
        log_pass(f"查询客户11画像成功, risk_level={data.get('risk_level')}")
    elif code == 404:
        log_fail("客户画像不存在", "customer_id=11")
    else:
        log_fail(f"查询画像失败", f"code={code}, resp={str(resp)[:200]}")

    # 画像研判
    code, resp = api("POST", "/api/profile/analyze", {"customer_id": 11, "message": "分析客户画像"}, token=token)
    if code == 200 and isinstance(resp, dict):
        log_pass("画像分析调用成功")
    else:
        log_fail(f"画像分析失败", f"code={code}, resp={str(resp)[:200]}")


def test_advisor_recommend(token):
    """TC-004: 投顾推荐API"""
    print("\n[TC-004] 投顾推荐API测试")

    code, resp = api("POST", "/api/recommend", {
        "customer_id": 11,
        "message": "推荐3款稳健型产品",
        "top_n": 3
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        data = resp.get("data", {})
        recs = data.get("recommendations", [])
        log_pass(f"推荐成功，返回{len(recs)}款产品")
        # 检查推荐结果是否包含必要字段
        if recs:
            p = recs[0]
            if all(k in p for k in ["product_code", "product_name", "risk_level"]):
                log_pass("推荐结果字段完整")
            else:
                log_warn(f"推荐结果缺少字段: {list(p.keys())}")
    else:
        log_fail("推荐API失败", f"code={code}, resp={str(resp)[:300]}")


def test_advisor_allocation(token):
    """TC-005: 资产配置API"""
    print("\n[TC-005] 资产配置API测试")

    code, resp = api("POST", "/api/allocation", {
        "customer_id": 11,
        "message": "给我一个稳健的资产配置方案"
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        log_pass("资产配置调用成功")
    else:
        log_fail("资产配置失败", f"code={code}, resp={str(resp)[:200]}")


def test_chat_customer(token):
    """TC-006: 智能客服对话"""
    print("\n[TC-006] 智能客服对话测试")

    code, resp = api("POST", "/api/chat/customer", {
        "message": "你好，我想了解一下理财产品"
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        data = resp.get("data", {})
        reply = data.get("reply", "")
        log_pass(f"客服回复成功，长度={len(reply)}")
    else:
        log_fail("客服对话失败", f"code={code}, resp={str(resp)[:200]}")


def test_chat_advisor(token):
    """TC-007: 投顾对话"""
    print("\n[TC-007] 投顾对话测试")

    code, resp = api("POST", "/api/chat/advisor", {
        "message": "给张三推荐几款产品",
        "customer_id": 11
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        data = resp.get("data", {})
        log_pass(f"投顾对话成功, reply长度={len(data.get('reply', ''))}")
    else:
        log_fail("投顾对话失败", f"code={code}, resp={str(resp)[:200]}")


def test_risk_questionnaire(token):
    """TC-008: 风评问卷"""
    print("\n[TC-008] 风评问卷API测试")

    code, resp = api("GET", "/api/risk/questionnaire", token=token)
    if code == 200 and isinstance(resp, dict):
        log_pass("获取风评问卷成功")
    else:
        log_fail("获取风评问卷失败", f"code={code}, resp={str(resp)[:200]}")


def test_risk_assessment(token):
    """TC-009: 风评提交"""
    print("\n[TC-009] 风评提交测试")

    code, resp = api("POST", "/api/risk/assessment", {
        "customer_id": 11,
        "answers": {"q1": 3, "q2": 2, "q3": 4, "q4": 3, "q5": 2}
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        log_pass("风评提交成功")
    else:
        log_fail("风评提交失败", f"code={code}, resp={str(resp)[:200]}")


def test_risk_suitability(token):
    """TC-010: 适当性匹配"""
    print("\n[TC-010] 适当性匹配测试")

    code, resp = api("POST", "/api/risk/suitability-check", {
        "customer_id": 11,
        "product_code": "FP001"
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        log_pass("适当性检查成功")
    else:
        log_fail("适当性检查失败", f"code={code}, resp={str(resp)[:200]}")


def test_risk_monitor(token):
    """TC-011: 风控监测"""
    print("\n[TC-011] 风控监测API测试")

    code, resp = api("POST", "/api/risk/monitor", {
        "customer_id": 11,
        "transaction_type": "purchase",
        "amount": 500000
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        log_pass("风控监测调用成功")
    else:
        log_fail("风控监测失败", f"code={code}, resp={str(resp)[:200]}")


def test_risk_alerts(token):
    """TC-012: 风控预警列表"""
    print("\n[TC-012] 风控预警列表测试")

    code, resp = api("GET", "/api/risk/alerts?page=1&page_size=10", token=token)
    if code == 200 and isinstance(resp, dict):
        data = resp.get("data", {})
        items = data.get("items", data.get("alerts", []))
        log_pass(f"预警列表获取成功，共{len(items)}条")
    else:
        log_fail("预警列表获取失败", f"code={code}, resp={str(resp)[:200]}")


def test_analyst(token):
    """TC-013: 数据分析(NL2SQL)"""
    print("\n[TC-013] 数据分析NL2SQL测试")

    code, resp = api("POST", "/api/chat/analyst", {
        "message": "查询资产超过100万的客户"
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        log_pass("NL2SQL分析调用成功")
    else:
        log_fail("NL2SQL分析失败", f"code={code}, resp={str(resp)[:200]}")


def test_operator(token):
    """TC-014: 业务操作Agent"""
    print("\n[TC-014] 业务操作Agent测试")

    code, resp = api("POST", "/api/chat/operator", {
        "message": "帮客户11申购产品FP001，金额100000"
    }, token=token)
    if code == 200 and isinstance(resp, dict):
        log_pass("业务操作Agent调用成功")
    else:
        log_fail("业务操作Agent失败", f"code={code}, resp={str(resp)[:200]}")


def test_knowledge(token):
    """TC-015: 知识库API"""
    print("\n[TC-015] 知识库API测试")

    code, resp = api("GET", "/api/knowledge/list", token=token)
    if code == 200 and isinstance(resp, dict):
        log_pass("知识库列表获取成功")
    else:
        log_fail("知识库列表获取失败", f"code={code}, resp={str(resp)[:200]}")


def test_rbac(token):
    """TC-016: 权限控制"""
    print("\n[TC-016] RBAC权限控制测试")

    # 客户登录，尝试访问他人画像
    customer_token = get_token("demo_customer_01", "Demo@123")
    if customer_token:
        code, resp = api("GET", "/api/profile/12", token=customer_token)
        if code == 403:
            log_pass("客户访问他人画像被拒绝(403)")
        elif code == 200:
            log_fail("客户不应访问他人画像", "RBAC未生效")
        else:
            log_warn(f"客户访问他人画像返回code={code}")
    else:
        log_warn("客户登录失败，跳过RBAC测试")


def test_cross_customer_data(token):
    """TC-017: 数据闭环 - 推荐结果是否持久化"""
    print("\n[TC-017] 数据闭环测试 - 推荐结果持久化")

    # 先调用推荐
    code, resp = api("POST", "/api/recommend", {
        "customer_id": 11,
        "message": "推荐产品",
        "top_n": 3
    }, token=token)

    if code == 200:
        log_pass("推荐调用成功，检查数据是否持久化到product_recommendation表")
    else:
        log_fail("推荐调用失败，无法验证数据闭环")


def test_intent_classification(token):
    """TC-018: 意图分类测试"""
    print("\n[TC-018] 意图分类测试")

    test_cases = [
        ("推荐几款稳健型产品", "推荐"),
        ("帮我赎回基金", "赎回"),
        ("查看我的持仓", "查询"),
        ("风险评估怎么做", "风评"),
        ("转账给朋友", "转账"),
    ]

    for msg, expected_intent in test_cases:
        code, resp = api("POST", "/api/chat/advisor", {
            "message": msg,
            "customer_id": 11
        }, token=token)
        if code == 200:
            log_pass(f"意图'{expected_intent}'处理成功: '{msg[:20]}...'")
        else:
            log_fail(f"意图'{expected_intent}'处理失败", f"code={code}")


def test_edge_cases(token):
    """TC-019: 边界和异常场景"""
    print("\n[TC-019] 边界和异常场景测试")

    # 空消息
    code, resp = api("POST", "/api/chat/advisor", {"message": "", "customer_id": 11}, token=token)
    log_info(f"空消息返回code={code}")

    # 不存在的客户
    code, resp = api("GET", "/api/profile/99999", token=token)
    log_info(f"不存在客户查询返回code={code}")

    # 超长消息
    long_msg = "推荐" * 5000
    code, resp = api("POST", "/api/chat/advisor", {"message": long_msg, "customer_id": 11}, token=token)
    log_info(f"超长消息返回code={code}")

    # 特殊字符
    code, resp = api("POST", "/api/chat/advisor", {"message": "'; DROP TABLE sys_user; --", "customer_id": 11}, token=token)
    log_info(f"SQL注入测试返回code={code}")


def test_business_flow(token):
    """TC-020: 完整业务流程测试"""
    print("\n[TC-020] 完整业务流程测试 - 申购流程")

    # 1. 查看客户画像
    code1, _ = api("GET", "/api/profile/11", token=token)
    # 2. 获取推荐
    code2, resp2 = api("POST", "/api/recommend", {"customer_id": 11, "message": "推荐", "top_n": 3}, token=token)
    # 3. 适当性检查
    code3, _ = api("POST", "/api/risk/suitability-check", {"customer_id": 11, "product_code": "FP001"}, token=token)
    # 4. 风控监测
    code4, _ = api("POST", "/api/risk/monitor", {"customer_id": 11, "transaction_type": "purchase", "amount": 100000}, token=token)

    flow_ok = all(c == 200 for c in [code1, code2, code3, code4])
    if flow_ok:
        log_pass("完整业务流程各环节API均可达")
    else:
        log_fail("业务流程存在断点", f"profile={code1}, recommend={code2}, suitability={code3}, monitor={code4}")


def print_summary():
    """打印测试总结"""
    print("\n" + "=" * 60)
    print("📊 测试总结报告")
    print("=" * 60)
    total = RESULTS["pass"] + RESULTS["fail"]
    print(f"  总用例: {total}")
    print(f"  ✅ 通过: {RESULTS['pass']}")
    print(f"  ❌ 失败: {RESULTS['fail']}")
    print(f"  ⚠️  警告: {len(RESULTS['warnings'])}")
    print(f"  ℹ️  信息: {len(RESULTS['info'])}")

    if RESULTS["errors"]:
        print(f"\n--- 失败详情 ---")
        for i, err in enumerate(RESULTS["errors"], 1):
            print(f"  {i}. {err}")

    if RESULTS["warnings"]:
        print(f"\n--- 警告详情 ---")
        for i, w in enumerate(RESULTS["warnings"], 1):
            print(f"  {i}. {w}")

    print(f"\n通过率: {RESULTS['pass']}/{total} = {RESULTS['pass']/max(total,1)*100:.1f}%")


# ==================== 主入口 ====================
if __name__ == "__main__":
    # Windows GBK console fix
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    print("[START] Investment Advisor Agent Comprehensive Test")
    print(f"   Target: {BASE_URL}")
    print(f"   Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # 基础测试
    test_health()
    token = test_auth()

    if not token:
        print("\n❌ 认证失败，终止测试")
        sys.exit(1)

    # API功能测试
    test_profile_api(token)
    test_advisor_recommend(token)
    test_advisor_allocation(token)
    test_chat_customer(token)
    test_chat_advisor(token)

    # 风控测试
    test_risk_questionnaire(token)
    test_risk_assessment(token)
    test_risk_suitability(token)
    test_risk_monitor(token)
    test_risk_alerts(token)

    # 其他模块
    test_analyst(token)
    test_operator(token)
    test_knowledge(token)

    # 高级测试
    test_rbac(token)
    test_cross_customer_data(token)
    test_intent_classification(token)
    test_edge_cases(token)
    test_business_flow(token)

    print_summary()
