"""申购二次确认全流程测试 — 覆盖 Redis 不可用的内存 fallback 场景。

Bug 背景：
- 修复前 Redis 连不上时，_save_pending_confirm 静默返回 False，但主流程仍然
  回复"请回复'确认'执行"。用户回复"确认"时 _load_pending_confirm 返回 None，
  导致 operator 回复"没有待确认的操作"——用户感知为"输入确认不会正确执行"。
- 修复前 _CONFIRM_RE 不支持中文标点，"确认。"/"确认！" 无法匹配；且无法识别
  "确认风险揭示" 作为风险披露的确认。
"""
import asyncio
import json
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent import operator_agent as OA


@pytest.fixture(autouse=True)
def _reset_fallback():
    """每个测试用例前后都重置 fallback 状态，避免用例间污染。"""
    OA._FALLBACK_ENABLED = False
    OA._FALLBACK_STORE.clear()
    yield
    OA._FALLBACK_ENABLED = False
    OA._FALLBACK_STORE.clear()


# =========================================================================
# 正则表达式回归测试（修复：支持中文标点 + "风险揭示"）
# =========================================================================
@pytest.mark.parametrize("text,should_match", [
    ("确认", True),
    ("确认。", True),        # 修复点 1：中文句号
    ("确认！", True),        # 修复点 1：中文感叹号
    ("确定", True),
    ("好的", True),
    ("y", True),
    ("yes", True),
    ("YES", True),
    ("确认风险揭示", True),  # 修复点 2：风险揭示确认
    ("确认风险揭示。", True),
    ("确认风险揭示 备注：客户坚持", True),
    ("确认 备注：客户主动要求", True),
    ("确认。备注：内部决定", True),
])
def test_confirm_regex_matches(text, should_match):
    assert bool(OA._CONFIRM_RE.match(text)) is should_match


@pytest.mark.parametrize("text", [
    "确认份额",         # 不应被误识别为二次确认
    "取消",             # 取消走另一个分支
    "申购10000",
    "帮我买基金",
    "",
])
def test_confirm_regex_rejects_non_confirm(text):
    assert not OA._CONFIRM_RE.match(text)


def test_confirm_regex_extract_note():
    m = OA._CONFIRM_RE.match("确认 备注：客户主动要求")
    assert m and m.group("note").strip() == "客户主动要求"


def test_confirm_regex_extract_disclosure():
    m = OA._CONFIRM_RE.match("确认风险揭示")
    assert m and m.group("disc")  # 能识别出这是风险揭示确认


def test_confirm_regex_non_disclosure_has_no_disc_group():
    m = OA._CONFIRM_RE.match("确认")
    assert m and not m.group("disc")


# =========================================================================
# Redis fallback 存储测试
# =========================================================================
@pytest.mark.asyncio
async def test_save_pending_confirm_falls_back_when_redis_down():
    """Redis 抛异常时，_save 应该返回 True（降级到内存），而不是 False。"""
    fake_redis = AsyncMock()
    fake_redis.setex = AsyncMock(side_effect=TimeoutError("Redis down"))

    with patch.object(OA, "get_redis", AsyncMock(return_value=fake_redis)):
        ok = await OA._save_pending_confirm(
            session_id="sess-1", action="purchase_product",
            arguments={"customer_name": "张三", "product_name": "稳健1号", "amount": 100000},
            user_id=42, user_role="理财顾问",
        )

    assert ok is True, "Redis 不可用时 _save 也应该返回 True（走 fallback）"
    assert OA._FALLBACK_ENABLED is True
    assert "42:sess-1" in OA._FALLBACK_STORE


@pytest.mark.asyncio
async def test_load_pending_confirm_after_fallback():
    """save 走了 fallback，load 也应该从内存取回相同的数据。"""
    fake_redis = AsyncMock()
    fake_redis.setex = AsyncMock(side_effect=TimeoutError("Redis down"))
    fake_redis.get = AsyncMock(side_effect=TimeoutError("Redis down"))

    args = {"customer_name": "张三", "product_name": "稳健1号", "amount": 100000}
    with patch.object(OA, "get_redis", AsyncMock(return_value=fake_redis)):
        await OA._save_pending_confirm(
            session_id="sess-1", action="purchase_product", arguments=args,
            user_id=42, user_role="理财顾问",
        )
        loaded = await OA._load_pending_confirm("sess-1", user_id=42)

    assert loaded is not None
    assert loaded["action"] == "purchase_product"
    assert loaded["arguments"] == args
    assert loaded["user_id"] == 42
    assert loaded["session_id"] == "sess-1"
    assert "summary" in loaded


@pytest.mark.asyncio
async def test_load_pending_confirm_returns_none_for_unknown_session():
    """没有 pending 的 session 应该返回 None。"""
    OA._FALLBACK_ENABLED = True
    loaded = await OA._load_pending_confirm("non-existent-session", user_id=999)
    assert loaded is None


@pytest.mark.asyncio
async def test_delete_pending_confirm_removes_fallback_entry():
    fake_redis = AsyncMock()
    fake_redis.setex = AsyncMock(side_effect=TimeoutError("Redis down"))
    fake_redis.delete = AsyncMock(side_effect=TimeoutError("Redis down"))

    with patch.object(OA, "get_redis", AsyncMock(return_value=fake_redis)):
        await OA._save_pending_confirm(
            session_id="sess-1", action="purchase_product",
            arguments={"customer_name": "张三", "product_name": "稳健1号", "amount": 10000},
            user_id=42, user_role="理财顾问",
        )
        assert "42:sess-1" in OA._FALLBACK_STORE

        await OA._delete_pending_confirm("sess-1", user_id=42)

    assert "42:sess-1" not in OA._FALLBACK_STORE


@pytest.mark.asyncio
async def test_fallback_entry_expires_after_ttl():
    """内存 fallback 的条目应该在 TTL 后过期。"""
    fake_redis = AsyncMock()
    fake_redis.setex = AsyncMock(side_effect=TimeoutError("Redis down"))

    with patch.object(OA, "get_redis", AsyncMock(return_value=fake_redis)):
        await OA._save_pending_confirm(
            session_id="sess-1", action="purchase_product",
            arguments={"customer_name": "张三", "product_name": "稳健1号", "amount": 10000},
            user_id=42, user_role="理财顾问",
        )

    # 手动把过期时间改成过去
    expire_ts, payload = OA._FALLBACK_STORE["42:sess-1"]
    OA._FALLBACK_STORE["42:sess-1"] = (expire_ts - 1000, payload)

    OA._fb_prune()
    assert "42:sess-1" not in OA._FALLBACK_STORE


@pytest.mark.asyncio
async def test_user_id_isolation_in_fallback():
    """不同 user_id 的 pending 应该相互隔离。"""
    fake_redis = AsyncMock()
    fake_redis.setex = AsyncMock(side_effect=TimeoutError("Redis down"))

    with patch.object(OA, "get_redis", AsyncMock(return_value=fake_redis)):
        await OA._save_pending_confirm(
            session_id="sess-shared", action="purchase_product",
            arguments={"customer_name": "张三"}, user_id=1, user_role="理财顾问",
        )
        await OA._save_pending_confirm(
            session_id="sess-shared", action="redeem_product",
            arguments={"customer_name": "李四"}, user_id=2, user_role="理财顾问",
        )

    loaded_1 = await OA._load_pending_confirm("sess-shared", user_id=1)
    loaded_2 = await OA._load_pending_confirm("sess-shared", user_id=2)
    assert loaded_1["arguments"]["customer_name"] == "张三"
    assert loaded_2["arguments"]["customer_name"] == "李四"


# =========================================================================
# 端到端：operator_chat 确认流程
# =========================================================================
@pytest.mark.asyncio
async def test_operator_chat_confirm_flow_with_redis_down():
    """模拟：用户先发起申购（触发 save），再回复"确认"（触发 load+execute）。

    整个流程在 Redis 不可用时应该仍能走通。
    """
    fake_redis = AsyncMock()
    fake_redis.setex = AsyncMock(side_effect=TimeoutError("Redis down"))
    fake_redis.get = AsyncMock(side_effect=TimeoutError("Redis down"))
    fake_redis.delete = AsyncMock(side_effect=TimeoutError("Redis down"))
    fake_redis.rpush = AsyncMock(side_effect=TimeoutError("Redis down"))
    fake_redis.lrange = AsyncMock(return_value=[])

    session_id = "e2e-session"
    user_id = 42

    # 第一步：模拟"待确认"状态已经存在（正常由第一次申购请求触发 _save 产生）
    with patch.object(OA, "get_redis", AsyncMock(return_value=fake_redis)):
        await OA._save_pending_confirm(
            session_id=session_id, action="purchase_product",
            arguments={"customer_name": "张三", "product_name": "稳健1号", "amount": 10000},
            user_id=user_id, user_role="理财顾问",
        )

    # 第二步：用户回复"确认。"（中文句号，修复前的 bug 场景）
    with patch.object(OA, "get_redis", AsyncMock(return_value=fake_redis)), \
         patch.object(OA, "execute_tool", AsyncMock(return_value={
             "success": True, "data": {"transaction_id": "TX001", "shares": 1000.0}
         })), \
         patch.object(OA, "_create_audit_work_order", AsyncMock()), \
         patch.object(OA, "publish_operation_event", AsyncMock()), \
         patch.object(OA, "SessionMemory") as mock_mem:
        mock_mem.return_value.add_message = AsyncMock()

        result = await OA.operator_chat(
            message="确认。",
            session_id=session_id,
            user_id=user_id,
            user_role="理财顾问",
        )

    # 修复前这里会返回"没有待确认的操作"，修复后应该执行成功
    assert result["status"] == "ok", f"预期执行成功，实际: {result.get('reply')}"
    assert "已确认执行" in result["reply"]
    assert result["action"] == "purchase_product"


@pytest.mark.asyncio
async def test_operator_chat_confirm_without_pending_politely_prompts():
    """没有 pending 时回复"确认"应该友好提示，而不是报错。"""
    fake_redis = AsyncMock()
    fake_redis.rpush = AsyncMock(side_effect=TimeoutError("Redis down"))
    fake_redis.lrange = AsyncMock(return_value=[])

    with patch.object(OA, "get_redis", AsyncMock(return_value=fake_redis)), \
         patch.object(OA, "SessionMemory") as mock_mem:
        mock_mem.return_value.add_message = AsyncMock()
        result = await OA.operator_chat(
            message="确认",
            session_id="fresh-session",
            user_id=1,
            user_role="理财顾问",
        )

    assert result["status"] == "ok"
    assert "没有待确认的操作" in result["reply"]
