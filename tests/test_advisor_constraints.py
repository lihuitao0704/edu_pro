from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.advisor_agent import AdvisorAgent
from app.service.advisor_narrative_service import AdvisorNarrativeService
from app.service.budget_allocation_service import BudgetAllocationService
from app.service.intent_service import IntentService


def test_budget_plan_never_allocates_below_product_minimum():
    plan = BudgetAllocationService.build(
        500_000,
        [
            {
                "product_code": "P-BOND",
                "product_name": "债券产品",
                "product_type": "债券型",
                "risk_level": "R2",
                "min_amount": 83_760.65,
            },
            {
                "product_code": "P-CASH-A",
                "product_name": "货币产品A",
                "product_type": "货币型",
                "risk_level": "R1",
                "min_amount": 1_894.72,
            },
            {
                "product_code": "P-CASH-B",
                "product_name": "货币产品B",
                "product_type": "货币型",
                "risk_level": "R2",
                "min_amount": 54_217.59,
            },
        ],
        {
            "allocation": {
                "债券类": 60,
                "货币类": 30,
                "现金": 10,
            }
        },
    )

    assert plan["constraint_valid"] is True
    assert plan["allocated_amount"] + plan["cash_reserve"] == 500_000
    assert all(
        item["amount"] >= item["min_amount"]
        for item in plan["product_allocations"]
    )


def test_budget_narrative_uses_validated_structured_amounts():
    result = {
        "customer_profile": {"risk_level": "C3"},
        "recommendations": [
            {
                "product_name": "稳健债券A",
                "product_type": "债券型",
                "risk_level": "R2",
                "min_amount": 10_000,
            }
        ],
    }
    plan = BudgetAllocationService.build(
        500_000,
        result["recommendations"],
        {"allocation": {"债券类": 60, "现金": 40}},
    )

    narrative = AdvisorNarrativeService.render_budget_plan(result, plan)

    assert "500,000 元配置方案" in narrative
    assert "起投 10,000.00 元" in narrative
    assert "规则引擎校验" in narrative


@pytest.mark.asyncio
async def test_streaming_advisor_rejects_employee_id_before_agent_execution():
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(
        first=lambda: SimpleNamespace(
            user_type="EMPLOYEE",
            employee_role="管理员",
            status="正常",
        )
    )
    agent = object.__new__(AdvisorAgent)
    agent.db = db
    agent.session_id = "stream-invalid"
    agent.memory = None
    agent._agent = AsyncMock()

    events = [
        event
        async for event in agent.stream_execute(
            "给客户ID 120推荐产品",
            customer_id=120,
            audience_role="管理员",
        )
    ]

    assert [event["type"] for event in events] == ["meta", "done"]
    assert events[-1]["status"] == "invalid_customer"
    assert "不是客户" in events[-1]["reply"]
    agent._agent.astream_events.assert_not_called()


def test_customer_entity_extraction_rejects_common_nouns():
    assert "customer_name" not in IntentService._extract_route_entities(
        "推荐适合稳健型客户的基金"
    )
    assert "customer_name" not in IntentService._extract_route_entities(
        "查询所有客户数据"
    )
    assert (
        IntentService._extract_route_entities("查询客户张三的持仓")[
            "customer_name"
        ]
        == "张三"
    )
