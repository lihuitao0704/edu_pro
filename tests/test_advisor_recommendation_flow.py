import inspect

from app.agent.advisor_agent import AdvisorAgent


def test_smart_recommend_does_not_share_one_session_with_asyncio_gather():
    source = inspect.getsource(AdvisorAgent._make_smart_recommend_tool)

    assert "profile_coro, alloc_coro" not in source
    assert "asyncio.gather(" not in source
