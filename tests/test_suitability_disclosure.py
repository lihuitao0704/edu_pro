from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.operator_agent import operator_chat
from app.api.operations.purchase import (
    _check_disclosure_position_cap,
    purchase_product,
)
from app.service.suitability_policy import (
    evaluate_suitability,
    validate_disclosure_ack,
)


def test_shared_policy_requires_disclosure_for_c3_r4_and_c4_r5():
    c3 = evaluate_suitability("C3", "R4")
    c4 = evaluate_suitability("进取型", "R5")

    assert c3.allowed is True
    assert c3.disclosure_required is True
    assert c3.max_position_ratio == 0.20
    assert c4.allowed is True
    assert c4.disclosure_required is True
    assert c4.max_position_ratio == 0.10


def test_shared_policy_blocks_unapproved_level():
    decision = evaluate_suitability("C2", "R4")

    assert decision.allowed is False
    assert decision.disclosure_required is False


def test_disclosure_ack_is_bound_to_rule_and_risk_levels():
    decision = evaluate_suitability("C3", "R4")
    acknowledgement = {
        "accepted": True,
        "rule_version": decision.rule_version,
        "rule_code": decision.rule_code,
        "customer_level": "C3",
        "product_level": "R4",
        "acknowledged_at": "2026-07-26T18:00:00",
    }

    assert validate_disclosure_ack(acknowledgement, decision) is True
    acknowledgement["product_level"] = "R5"
    assert validate_disclosure_ack(acknowledgement, decision) is False


@pytest.mark.asyncio
async def test_plain_confirmation_does_not_accept_pending_risk_disclosure():
    memory = AsyncMock()
    pending = {
        "action": "purchase_product",
        "arguments": {
            "customer_name": "张三",
            "product_name": "R4产品",
            "amount": 10000,
        },
        "user_id": 9,
        "user_role": "理财顾问",
        "summary": "申购确认",
        "risk_disclosure": {
            **evaluate_suitability("C3", "R4").to_dict(),
            "text": "C3 客户购买 R4 产品前必须确认风险揭示",
        },
    }
    with (
        patch("app.agent.operator_agent.SessionMemory", return_value=memory),
        patch(
            "app.agent.operator_agent._load_pending_confirm",
            new=AsyncMock(return_value=pending),
        ),
        patch(
            "app.agent.operator_agent.execute_tool",
            new=AsyncMock(),
        ) as execute,
    ):
        result = await operator_chat(
            "确认",
            session_id="disclosure-session",
            user_id=9,
            user_role="理财顾问",
        )

    assert result["status"] == "disclosure_required"
    assert "确认风险揭示" in result["reply"]
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_disclosure_confirmation_injects_auditable_ack():
    memory = AsyncMock()
    pending = {
        "action": "purchase_product",
        "arguments": {
            "customer_name": "张三",
            "product_name": "R4产品",
            "amount": 10000,
        },
        "user_id": 9,
        "user_role": "理财顾问",
        "summary": "申购确认",
        "risk_disclosure": {
            **evaluate_suitability("C3", "R4").to_dict(),
            "text": "C3 客户购买 R4 产品前必须确认风险揭示",
        },
    }
    tool_result = {
        "success": True,
        "data": {
            "transaction_no": "TX001",
            "product_name": "R4产品",
            "amount": 10000,
            "shares": 1000,
            "nav_date": "2026-07-26",
        },
    }
    with (
        patch("app.agent.operator_agent.SessionMemory", return_value=memory),
        patch(
            "app.agent.operator_agent._load_pending_confirm",
            new=AsyncMock(return_value=pending),
        ),
        patch(
            "app.agent.operator_agent._delete_pending_confirm",
            new=AsyncMock(),
        ),
        patch(
            "app.agent.operator_agent.execute_tool",
            new=AsyncMock(return_value=tool_result),
        ) as execute,
        patch(
            "app.agent.operator_agent._create_audit_work_order",
            new=AsyncMock(),
        ),
        patch(
            "app.agent.operator_agent.publish_operation_event",
            new=AsyncMock(),
        ),
        patch(
            "app.agent.operator_agent._archive_memory",
            new=AsyncMock(),
        ),
    ):
        result = await operator_chat(
            "确认风险揭示",
            session_id="disclosure-session",
            user_id=9,
            user_role="理财顾问",
        )

    assert result["status"] == "ok"
    arguments = execute.await_args.args[1]
    acknowledgement = arguments["risk_disclosure_ack"]
    assert acknowledgement["accepted"] is True
    assert acknowledgement["rule_code"] == "SD-C3-R4"
    assert acknowledgement["acknowledged_by"] == 9
    assert acknowledgement["acknowledged_at"]


@pytest.mark.asyncio
async def test_purchase_api_rejects_missing_disclosure_ack():
    product_result = MagicMock()
    product_result.mappings.return_value.first.return_value = {
        "id": 4,
        "product_name": "R4产品",
        "risk_level": "R4",
        "status": "在售",
        "min_amount": 1000,
    }
    profile_result = MagicMock()
    profile_result.mappings.return_value.first.return_value = {"risk_level": "C3"}
    db = AsyncMock()
    db.execute.side_effect = [product_result, profile_result]

    result = await purchase_product(
        body={
            "customer_id": 7,
            "product_id": 4,
            "amount": 10000,
            "operator_id": 9,
        },
        db=db,
        user={"user_id": 9, "role": "理财顾问"},
    )

    assert result.code == 428
    assert "风险揭示" in result.message
    assert result.data["risk_disclosure"]["rule_code"] == "SD-C3-R4"


@pytest.mark.asyncio
async def test_disclosure_position_cap_uses_total_assets_and_existing_holding():
    total_assets = MagicMock()
    total_assets.scalar.return_value = 100000
    existing_holding = MagicMock()
    existing_holding.scalar.return_value = 10000
    db = AsyncMock()
    db.execute.side_effect = [total_assets, existing_holding]

    allowed, message = await _check_disclosure_position_cap(
        db,
        customer_id=7,
        product_id=4,
        amount=5000,
        max_position_ratio=0.20,
    )

    assert allowed is True
    assert message == ""


@pytest.mark.asyncio
async def test_disclosure_position_cap_blocks_excess_concentration():
    total_assets = MagicMock()
    total_assets.scalar.return_value = 100000
    existing_holding = MagicMock()
    existing_holding.scalar.return_value = 10000
    db = AsyncMock()
    db.execute.side_effect = [total_assets, existing_holding]

    allowed, message = await _check_disclosure_position_cap(
        db,
        customer_id=7,
        product_id=4,
        amount=15000,
        max_position_ratio=0.20,
    )

    assert allowed is False
    assert "25.00%" in message
    assert "20%" in message
