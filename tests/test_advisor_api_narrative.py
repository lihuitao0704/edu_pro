import asyncio

from app.api import advisor
from app.model.schemas import AdvisorChatRequest


def test_advisor_api_returns_a_displayable_narrative_with_disclaimer(monkeypatch):
    class StubAdvisorAgent:
        def __init__(self, *_args, **_kwargs):
            pass

        async def execute(self, *_args, **_kwargs):
            return {
                "reply": "已完成客户画像匹配。",
                "recommendations": [{"product_name": "稳健债券A"}],
                "customer_profile": {"assessment": {"risk_level": "C3"}},
                "reasoning": "画像与产品风险等级匹配。",
            }

    monkeypatch.setattr(advisor, "AdvisorAgent", StubAdvisorAgent)
    monkeypatch.setattr(advisor, "enforce_customer_scope", lambda *_args: None)

    response = asyncio.run(advisor.advisor_chat(
            AdvisorChatRequest(session_id="test", message="推荐产品", user_id=1, customer_id=1),
            db=object(),
            user={"role": "管理员"},
        )
    )

    assert response["data"]["narrative"] == response["data"]["reply"]
    assert "投资有风险，入市需谨慎" in response["data"]["reply"]


def test_holdings_analysis_uses_an_explicit_customer_id(monkeypatch):
    received = {}

    class StubAdvisorAgent:
        def __init__(self, *_args, **_kwargs):
            pass

        async def execute(self, message, *, customer_id):
            received["message"] = message
            received["customer_id"] = customer_id
            return {"holdings_analysis": {"total_value": 100000}}

    monkeypatch.setattr(advisor, "AdvisorAgent", StubAdvisorAgent)
    monkeypatch.setattr(advisor, "enforce_customer_scope", lambda *_args: None)

    response = asyncio.run(advisor.holdings_analysis(
        advisor.AllocationRequest(customer_id=7), db=object(), user={"role": "管理员"}
    ))

    assert received == {"message": "分析持仓", "customer_id": 7}
    assert response["data"]["holdings_analysis"]["total_value"] == 100000
