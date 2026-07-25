"""
风控Agent客服与画像联动测试脚本
测试文档：风控Agent_客服与画像测试结果.md
"""
import asyncio
import sys
import os
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.database import async_session_factory
from app.agent.router_agent import RouterAgent
from app.agent.customer_agent import CustomerServiceAgent
from app.service.profile_service import ProfileService
from sqlalchemy import text


async def test_c4_risk_intercept():
    """测试1: 客服Agent风控联动（C4）"""
    print("\n" + "="*60)
    print("测试1: 客服Agent风控联动（C4）")
    print("="*60)
    print("输入: demo_customer_01 (risk_flag=high) 输入 '我想大额转账'")
    print("预期: 回复中应包含风控提示")
    print("-"*60)

    async with async_session_factory() as db:
        # 验证 risk_flag
        result = await db.execute(
            text("SELECT risk_flag FROM fin_customer_profile WHERE customer_id = 1")
        )
        risk_flag = result.scalar()
        print(f"[数据验证] demo_customer_01 risk_flag = {risk_flag}")

        # 模拟路由
        router = RouterAgent(db)
        response = await router.route(
            message="我想大额转账",
            session_id="test_session_1",
            user_id=1,  # demo_customer_01
            user_role="客户"
        )

        print(f"\n[路由结果]")
        print(f"  intent: {response.intent}")
        print(f"  agent: {response.agent}")
        print(f"  reply: {response.reply[:200]}...")

        # 检查是否包含风控提示
        has_risk_warning = "风控" in response.reply or "风险" in response.reply or "预警" in response.reply
        print(f"\n[测试结果] {'[PASS]' if has_risk_warning else '[FAIL]'}")
        print(f"  是否包含风控提示: {has_risk_warning}")

        return has_risk_warning


async def test_customer_id_mapping():
    """测试2: 客户画像AML风险等级展示 - 客户ID映射"""
    print("\n" + "="*60)
    print("测试2: 客户ID映射验证")
    print("="*60)
    print("输入: demo_customer_05")
    print("预期: 应映射到客户ID=5")
    print("-"*60)

    from app.tool.graph_query_tool import resolve_customer_id

    # 测试名字解析
    customer_id = await resolve_customer_id("演示客户05")
    print(f"[解析结果] '演示客户05' -> ID={customer_id}")

    # 验证数据库
    async with async_session_factory() as db:
        result = await db.execute(
            text("SELECT id, username, real_name FROM sys_user WHERE username = 'demo_customer_05'")
        )
        row = result.first()
        if row:
            print(f"[数据验证] username=demo_customer_05 -> ID={row[0]}, real_name={row[2]}")

    is_correct = customer_id == 5
    print(f"\n[测试结果] {'[PASS]' if is_correct else '[FAIL]'}")
    print(f"  ID映射是否正确: {is_correct}")

    return is_correct


async def test_aml_risk_level():
    """测试3: 客户画像AML风险等级展示"""
    print("\n" + "="*60)
    print("测试3: 客户画像AML风险等级展示")
    print("="*60)
    print("输入: demo_customer_05 (有3条预警)")
    print("预期: 画像应包含 aml_risk_level='high'")
    print("-"*60)

    async with async_session_factory() as db:
        # 验证预警数量
        result = await db.execute(
            text("SELECT COUNT(*) FROM fin_risk_alert WHERE customer_id = 5")
        )
        alert_count = result.scalar()
        print(f"[数据验证] demo_customer_05 预警数量 = {alert_count}")

        # 查询画像（含AML等级）
        service = ProfileService(db)
        profile = await service.get_profile(5)
        if not profile:
            print("[错误] 画像不存在")
            return False

        profile_data = service._profile_to_dict(profile)
        aml_info = await service.get_aml_risk_level(5)
        profile_data.update(aml_info)

        print(f"\n[画像数据]")
        print(f"  customer_id: {profile_data['customer_id']}")
        print(f"  risk_level: {profile_data['risk_level']}")
        print(f"  risk_score: {profile_data['risk_score']}")
        print(f"  risk_flag: {profile_data['risk_flag']}")
        print(f"  aml_risk_level: {profile_data.get('aml_risk_level')}")
        print(f"  alert_count_30d: {profile_data.get('alert_count_30d')}")

        # 验证AML等级
        aml_level = profile_data.get('aml_risk_level')
        is_correct = aml_level == 'high' and alert_count >= 3
        print(f"\n[测试结果] {'[PASS]' if is_correct else '[FAIL]'}")
        print(f"  AML等级是否正确: {aml_level == 'high'}")

        return is_correct


async def test_normal_customer_no_intercept():
    """测试4: 正常客户不被拦截"""
    print("\n" + "="*60)
    print("测试4: 正常客户不被拦截")
    print("="*60)
    print("输入: demo_customer_02 (risk_flag=normal) 输入 '我想大额转账'")
    print("预期: 正常路由到业务操作Agent，不拦截")
    print("-"*60)

    async with async_session_factory() as db:
        # 验证 risk_flag
        result = await db.execute(
            text("SELECT risk_flag FROM fin_customer_profile WHERE customer_id = 2")
        )
        risk_flag = result.scalar()
        print(f"[数据验证] demo_customer_02 risk_flag = {risk_flag}")

        # 模拟路由
        router = RouterAgent(db)
        response = await router.route(
            message="我想大额转账",
            session_id="test_session_2",
            user_id=2,  # demo_customer_02
            user_role="客户"
        )

        print(f"\n[路由结果]")
        print(f"  intent: {response.intent}")
        print(f"  agent: {response.agent}")

        # 检查是否被拦截
        is_intercepted = response.intent == "risk_intercepted"
        is_normal = not is_intercepted
        print(f"\n[测试结果] {'[PASS]' if is_normal else '[FAIL]'}")
        print(f"  是否未被拦截: {is_normal}")

        return is_normal


async def main():
    print("\n" + "="*60)
    print("风控Agent客服与画像联动测试")
    print("="*60)

    results = []

    # 测试1: C4风控联动
    try:
        result1 = await test_c4_risk_intercept()
        results.append(("C4风控联动", result1))
    except Exception as e:
        print(f"[错误] 测试1异常: {e}")
        results.append(("C4风控联动", False))

    # 测试2: 客户ID映射
    try:
        result2 = await test_customer_id_mapping()
        results.append(("客户ID映射", result2))
    except Exception as e:
        print(f"[错误] 测试2异常: {e}")
        results.append(("客户ID映射", False))

    # 测试3: AML风险等级
    try:
        result3 = await test_aml_risk_level()
        results.append(("AML风险等级", result3))
    except Exception as e:
        print(f"[错误] 测试3异常: {e}")
        results.append(("AML风险等级", False))

    # 测试4: 正常客户不拦截
    try:
        result4 = await test_normal_customer_no_intercept()
        results.append(("正常客户不拦截", result4))
    except Exception as e:
        print(f"[错误] 测试4异常: {e}")
        results.append(("正常客户不拦截", False))

    # 汇总
    print("\n" + "="*60)
    print("测试汇总")
    print("="*60)
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {name}: {status}")

    total = len(results)
    passed = sum(1 for _, p in results if p)
    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n[SUCCESS] 所有测试通过！")
    else:
        print(f"\n[WARNING] {total - passed} 个测试失败")


if __name__ == "__main__":
    asyncio.run(main())
