import pytest
from unittest.mock import AsyncMock

from app.model.route_decision import RouteDomain, RouteTask
from app.service.intent_service import IntentService
from app.service.route_validator import RouteValidator


@pytest.mark.parametrize(
    ("message", "task", "domain", "intent"),
    [
        ("有什么年化5%以上的稳健型理财", RouteTask.FAQ, RouteDomain.PRODUCT, "product_faq"),
        ("最新监管政策对私募基金有什么要求", RouteTask.FAQ, RouteDomain.POLICY, "product_faq"),
        ("赎回手续费怎么收", RouteTask.FAQ, RouteDomain.TRANSACTION, "product_faq"),
        ("你好", RouteTask.CHAT, RouteDomain.GENERAL, "chitchat"),
        ("我想了解一下你们的服务", RouteTask.FAQ, RouteDomain.GENERAL, "product_faq"),
        ("帮我写一首诗", RouteTask.CHAT, RouteDomain.GENERAL, "chitchat"),
        ("帮我推荐适合我的基金", RouteTask.RECOMMEND, RouteDomain.PRODUCT, "investment_recommendation"),
        ("分析一下我的持仓行业分布", RouteTask.ANALYZE, RouteDomain.HOLDING, "investment_recommendation"),
        ("50万资金应该怎么配置", RouteTask.RECOMMEND, RouteDomain.GENERAL, "investment_recommendation"),
        ("对比一下这两个产品", RouteTask.ANALYZE, RouteDomain.PRODUCT, "investment_recommendation"),
        ("帮我查一下最近的可疑交易", RouteTask.RISK_CHECK, RouteDomain.RISK, "risk_control"),
        ("检测一下有没有异常转账", RouteTask.RISK_CHECK, RouteDomain.RISK, "risk_control"),
        ("查询资产超过100万的客户", RouteTask.QUERY, RouteDomain.CUSTOMER, "data_analysis"),
        ("统计各产品类型的平均收益率", RouteTask.QUERY, RouteDomain.PRODUCT, "data_analysis"),
        ("查询客户张三的持仓", RouteTask.QUERY, RouteDomain.HOLDING, "data_analysis"),
        ("查一下近30天的交易记录", RouteTask.QUERY, RouteDomain.TRANSACTION, "data_analysis"),
        ("查询所有在售产品", RouteTask.QUERY, RouteDomain.PRODUCT, "data_analysis"),
        ("查一下工单处理进度", RouteTask.QUERY, RouteDomain.WORK_ORDER, "data_analysis"),
        ("给客户A申购10万XX产品", RouteTask.EXECUTE, RouteDomain.TRANSACTION, "business_operation"),
        ("把客户A的50万转到客户B", RouteTask.EXECUTE, RouteDomain.TRANSACTION, "business_operation"),
        ("帮我赎回客户B持有的XX全部份额", RouteTask.EXECUTE, RouteDomain.TRANSACTION, "business_operation"),
        ("上报可疑交易", RouteTask.EXECUTE, RouteDomain.RISK, "business_operation"),
    ],
)
def test_report_cases_have_deterministic_route(message, task, domain, intent):
    decision = IntentService._rule_route_decision(message)

    assert decision is not None
    assert decision.task == task
    assert decision.domain == domain
    assert decision.intent == intent


def test_bare_confirmation_requires_operator_context():
    ambiguous = IntentService._rule_route_decision("确认")
    operation = IntentService._rule_route_decision(
        "确认",
        context={"last_agent": "operator", "last_intent": "business_operation"},
    )

    assert ambiguous.task == RouteTask.UNKNOWN
    assert ambiguous.confidence < 0.70
    assert operation.task == RouteTask.EXECUTE
    assert operation.target_agent == "operator"


def test_clarification_choice_reuses_pending_domain_and_entities():
    decision = IntentService._rule_route_decision(
        "查询明细或状态",
        context={
            "pending_route_decision": {
                "domain": "HOLDING",
                "entities": {"customer_name": "张三"},
            }
        },
    )

    assert decision.task == RouteTask.QUERY
    assert decision.domain == RouteDomain.HOLDING
    assert decision.entities["customer_name"] == "张三"
    assert decision.decision_source == "clarification_choice"


def test_low_confidence_is_clarified_instead_of_defaulting_to_customer_service():
    decision = IntentService._build_route_decision(
        "看看这个",
        RouteTask.UNKNOWN,
        RouteDomain.UNKNOWN,
        confidence=0.2,
        source="fallback",
    )

    validated = RouteValidator().validate(decision, user_role="客户")

    assert validated.intent == "clarification"
    assert validated.target_agent == "router"
    assert validated.needs_clarification is True


def test_customer_cannot_route_to_unrestricted_data_analysis():
    decision = IntentService._build_route_decision(
        "查询所有客户",
        RouteTask.QUERY,
        RouteDomain.CUSTOMER,
    )

    validated = RouteValidator().validate(decision, user_role="客户")

    assert validated.blocked is True
    assert "保护客户隐私" in validated.block_reason
    assert "查询我的持仓" in validated.block_reason


def test_write_operation_requires_confirmation():
    decision = IntentService._rule_route_decision("帮我赎回10万元")

    validated = RouteValidator().validate(decision, user_role="客户")

    assert validated.requires_confirmation is True
    assert validated.target_agent == "operator"


@pytest.mark.asyncio
async def test_router_returns_clarification_without_dispatching_an_agent():
    from app.agent.router_agent import RouterAgent

    router = RouterAgent(AsyncMock())
    unknown = IntentService._build_route_decision(
        "看看这个",
        RouteTask.UNKNOWN,
        RouteDomain.UNKNOWN,
        confidence=0.2,
        source="fallback",
    )
    unknown.needs_clarification = True
    router.intent_service.decide_route = AsyncMock(return_value=unknown)
    router._risk_precheck = AsyncMock(return_value=None)
    router._dispatch_customer_service = AsyncMock()

    response = await router.route("看看这个", user_id=7, user_role="客户")

    assert response.intent == "clarification"
    assert response.agent == "router"
    assert response.data["clarification"]["choices"]
    router._dispatch_customer_service.assert_not_awaited()


@pytest.mark.asyncio
async def test_router_reuses_precomputed_decision_without_classifying_again():
    from app.agent.router_agent import RouterAgent

    router = RouterAgent(AsyncMock())
    decision = IntentService._build_route_decision(
        "赎回手续费怎么收",
        RouteTask.FAQ,
        RouteDomain.TRANSACTION,
    )
    router.intent_service.decide_route = AsyncMock()
    router._risk_precheck = AsyncMock(return_value=None)
    router._dispatch_customer_service = AsyncMock(
        return_value={"reply": "手续费说明", "data": {}}
    )

    response = await router.route(
        "赎回手续费怎么收",
        user_id=7,
        user_role="客户",
        route_decision=decision,
    )

    assert response.intent == "product_faq"
    assert response.agent == "customer_service"
    router.intent_service.decide_route.assert_not_awaited()


@pytest.mark.asyncio
async def test_supervisor_failure_falls_back_to_clarification_not_faq():
    service = IntentService()
    service.llm.classify = AsyncMock(side_effect=RuntimeError("model unavailable"))

    decision = await service.decide_route("帮我看看这个", user_role="客户")

    assert decision.intent == "clarification"
    assert decision.target_agent == "router"
    assert decision.needs_clarification is True
    assert decision.decision_source == "fallback"


def test_supervisor_json_is_parsed_into_two_dimensional_decision():
    decision = IntentService._parse_supervisor_decision(
        """
        {"task":"QUERY","domain":"WORK_ORDER","confidence":0.82,
         "alternatives":["EXECUTE"],
         "entities":{"customer_id":7},
         "clarification_question":null}
        """,
        "查看工单",
    )

    assert decision.task == RouteTask.QUERY
    assert decision.domain == RouteDomain.WORK_ORDER
    assert decision.intent == "data_analysis"
    assert decision.target_agent == "nl2sql"
    assert decision.entities["customer_id"] == 7


@pytest.mark.asyncio
async def test_compound_plan_splits_greeting_recommendation_and_customer_query():
    service = IntentService()

    plan = await service.plan_route(
        "你好,，帮我推荐适合稳健型客户的基金，顺便帮我查询所有客户数据",
        user_role="理财顾问",
    )

    assert plan.is_multi_intent is True
    assert plan.execution_mode == "safe_sequential"
    assert [(item.task, item.domain) for item in plan.tasks] == [
        (RouteTask.RECOMMEND, RouteDomain.PRODUCT),
        (RouteTask.QUERY, RouteDomain.CUSTOMER),
    ]
    assert all(item.task != RouteTask.CHAT for item in plan.tasks)


@pytest.mark.asyncio
async def test_router_executes_authorized_read_only_compound_plan():
    from app.agent.router_agent import RouterAgent

    router = RouterAgent(AsyncMock())
    router.intent_service = IntentService()
    plan = await router.intent_service.plan_route(
        "你好，帮我推荐适合稳健型客户的基金，顺便帮我查询所有客户数据",
        user_role="理财顾问",
    )
    router._risk_precheck = AsyncMock(return_value=None)
    router._dispatch_advisor = AsyncMock(
        return_value={
            "reply": "已生成稳健型基金建议。",
            "data": {"recommendations": [{"name": "稳健基金A"}]},
        }
    )
    router._dispatch_data_analysis = AsyncMock(
        return_value={
            "reply": "已查询客户数据。",
            "data": {"query_result": [{"customer_id": 1}]},
        }
    )

    response = await router.route(
        plan.original_message,
        user_id=7,
        user_role="理财顾问",
        route_plan=plan,
    )

    assert response.intent == "multi_intent"
    assert response.agent == "router_supervisor"
    assert response.data["partial_success"] is False
    assert [item["status"] for item in response.data["task_results"]] == [
        "completed",
        "completed",
    ]
    assert response.data["recommendations"][0]["name"] == "稳健基金A"
    assert response.data["query_result"][0]["customer_id"] == 1
    router._dispatch_advisor.assert_awaited_once()
    router._dispatch_data_analysis.assert_awaited_once()


@pytest.mark.asyncio
async def test_customer_compound_plan_returns_partial_result_and_blocks_customer_list():
    from app.agent.router_agent import RouterAgent

    router = RouterAgent(AsyncMock())
    router.intent_service = IntentService()
    plan = await router.intent_service.plan_route(
        "帮我推荐适合稳健型客户的基金，顺便帮我查询所有客户数据",
        user_role="客户",
    )
    router._risk_precheck = AsyncMock(return_value=None)
    router._dispatch_advisor = AsyncMock(
        return_value={"reply": "已生成基金建议。", "data": {}}
    )
    router._dispatch_data_analysis = AsyncMock()

    response = await router.route(
        plan.original_message,
        user_id=7,
        user_role="客户",
        route_plan=plan,
    )

    assert response.intent == "multi_intent"
    assert response.data["partial_success"] is True
    assert [item["status"] for item in response.data["task_results"]] == [
        "completed",
        "blocked",
    ]
    assert "保护客户隐私" in response.data["task_results"][1]["reply"]
    router._dispatch_advisor.assert_awaited_once()
    router._dispatch_data_analysis.assert_not_awaited()


@pytest.mark.asyncio
async def test_compound_write_task_is_not_dispatched_without_separate_confirmation():
    from app.agent.router_agent import RouterAgent

    router = RouterAgent(AsyncMock())
    router.intent_service = IntentService()
    plan = await router.intent_service.plan_route(
        "帮我推荐一只稳健基金，然后帮我赎回10万元",
        user_role="客户",
    )
    router._risk_precheck = AsyncMock(return_value=None)
    router._dispatch_advisor = AsyncMock(
        return_value={"reply": "已生成基金建议。", "data": {}}
    )
    router._dispatch_operator = AsyncMock()

    response = await router.route(
        plan.original_message,
        user_id=7,
        user_role="客户",
        route_plan=plan,
    )

    assert response.data["partial_success"] is True
    assert response.data["task_results"][1]["status"] == (
        "requires_separate_confirmation"
    )
    router._dispatch_operator.assert_not_awaited()


def test_product_risk_level_query_routes_to_product_data_not_risk_monitor():
    decision = IntentService._rule_route_decision("查询R2风险等级的产品")

    assert decision.task == RouteTask.QUERY
    assert decision.domain == RouteDomain.PRODUCT
    assert decision.target_agent == "nl2sql"
    assert decision.entities["risk_level"] == "R2"


def test_explicit_customer_id_with_copula_and_amount_continues_recommendation():
    decision = IntentService._rule_route_decision(
        "客户ID是120的，他要投资50万"
    )

    assert decision.task == RouteTask.RECOMMEND
    assert decision.target_agent == "advisor"
    assert decision.entities["customer_id"] == 120
    assert decision.entities["amount"] == 500000


def test_pronoun_amount_followup_inherits_advisor_customer():
    decision = IntentService._rule_route_decision(
        "他要投资50万",
        context={
            "last_agent": "advisor",
            "last_intent": "investment_recommendation",
            "entities": {"customer_id": 120},
        },
    )

    assert decision.task == RouteTask.RECOMMEND
    assert decision.entities["customer_id"] == 120
    assert decision.entities["amount"] == 500000


def test_entity_tracker_keeps_customer_id_for_pronoun_followup():
    from app.common_services.context_manager.entity_tracker import EntityTracker

    tracker = EntityTracker()
    first = tracker.track("客户ID是120的")
    followup = tracker.track("他要投资50万", first)

    assert first["customer_id"] == 120
    assert followup["customer_id"] == 120
    assert followup["amount"] == 500000


def test_restricted_allocation_does_not_include_mixed_or_equity_assets():
    from app.agent.advisor_agent import AdvisorAgent

    constrained = AdvisorAgent._constrain_allocation(
        {},
        customer_id=120,
        max_allowed_risk=2,
        original_risk_level="C3",
    )

    assert constrained["constraint_applied"] is True
    assert constrained["risk_level"] == "C2"
    assert constrained["allocation"]["混合类"] == 0
    assert constrained["allocation"]["股票类"] == 0
