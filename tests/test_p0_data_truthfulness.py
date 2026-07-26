from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_advisor_loads_isolated_active_product_snapshots():
    from app.service.advisor_service import AdvisorService

    product = SimpleNamespace(
        id=7,
        product_code="PROD-0007",
        product_name="消费混合灵活配置07号",
        product_type="混合型",
        risk_level="R2",
        expected_return=Decimal("5.8400"),
        min_amount=Decimal("8007.81"),
        term_days=180,
        create_time=datetime(2026, 7, 20, 9, 0),
        update_time=datetime(2026, 7, 25, 15, 52, 50),
    )
    result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [product])
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    service = AdvisorService(db)

    first = await service._load_active_products(["R1", "R2"])
    second = await service._load_active_products(["R1", "R2"])

    assert first == second
    assert first is not second
    assert first[0] is not second[0]
    assert first[0]["product_id"] == 7
    assert first[0]["data_source"] == "fin_product"
    assert first[0]["product_snapshot_time"] == "2026-07-25T15:52:50"
    assert first[0]["expected_return"] == 5.84


def test_product_quality_gate_rejects_misclassified_or_implausible_products():
    from app.service.advisor_service import AdvisorService

    products = [
        {
            "product_id": 1,
            "product_code": "SAFE-BOND",
            "product_name": "稳健纯债",
            "product_type": "债券型",
            "risk_level": "R2",
            "expected_return": 4.2,
        },
        {
            "product_id": 2,
            "product_code": "BAD-EQUITY",
            "product_name": "消费股票价值精选",
            "product_type": "股票型",
            "risk_level": "R1",
            "expected_return": 8.2,
        },
        {
            "product_id": 3,
            "product_code": "BAD-CASH",
            "product_name": "货币现金管理",
            "product_type": "货币型",
            "risk_level": "R2",
            "expected_return": 13.14,
        },
    ]

    filtered = AdvisorService._filter_product_quality(products)

    assert [product["product_code"] for product in filtered] == ["SAFE-BOND"]


@pytest.mark.asyncio
async def test_recommendation_reason_is_deterministic_and_does_not_call_llm():
    from app.service.advisor_service import AdvisorService

    service = object.__new__(AdvisorService)
    service._llm = SimpleNamespace(chat=AsyncMock())
    reason = await service._generate_reason(
        {
            "product_name": "稳健纯债",
            "product_type": "债券型",
            "risk_level": "R2",
            "expected_return": 4.2,
        },
        "C3",
        None,
    )

    assert "平衡型" in reason
    assert len(reason) <= 80
    service._llm.chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_advisor_rejects_employee_id_before_running_any_agent_tool():
    from app.agent.advisor_agent import AdvisorAgent

    identity = SimpleNamespace(
        user_type="EMPLOYEE",
        employee_role="管理员",
        status="正常",
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(first=lambda: identity)
        )
    )
    agent = object.__new__(AdvisorAgent)
    agent.db = db
    agent.session_id = "identity-test"

    result = await agent.execute("给他推荐产品", customer_id=120)

    assert result["status"] == "invalid_customer"
    assert result["recommendations"] == []
    assert "管理员账号，不是客户" in result["reply"]


@pytest.mark.asyncio
async def test_cumulative_risk_alert_reuses_legacy_record_without_inserting():
    from app.service.risk_scheduler import _upsert_cumulative_risk_alert

    existing = SimpleNamespace(
        reminder_key=None,
        alert_level="medium",
        trigger_detail="旧内容",
        transaction_ids={},
        update_time=None,
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: existing)
        )
    )
    now = datetime(2026, 7, 26, 3, 0)

    inserted = await _upsert_cumulative_risk_alert(
        db, customer_id=5, cumulative_count=4, now=now
    )

    assert inserted is False
    assert db.execute.await_count == 1
    assert existing.reminder_key == "cumulative_risk:5:2026-07-26"
    assert existing.alert_level == "high"
    assert existing.transaction_ids["cumulative_count"] == 4


@pytest.mark.asyncio
async def test_cumulative_risk_alert_uses_unique_insert_for_new_record():
    from app.service.risk_scheduler import _upsert_cumulative_risk_alert

    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: None),
                SimpleNamespace(rowcount=1),
            ]
        )
    )
    now = datetime(2026, 7, 26, 3, 0)

    inserted = await _upsert_cumulative_risk_alert(
        db, customer_id=1, cumulative_count=6, now=now
    )

    assert inserted is True
    insert_params = db.execute.await_args_list[1].args[1]
    assert insert_params["reminder_key"] == "cumulative_risk:1:2026-07-26"
    assert '"cumulative_count": 6' in insert_params["payload"]
