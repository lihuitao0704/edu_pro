"""
业务操作 Agent (operator_agent) 单元测试 + 集成测试
覆盖范围:
  1. 纯函数 (_safe_float, _check_self_transfer, _check_trading_hours)
  2. RBAC 权限矩阵
  3. 二次确认阈值逻辑
  4. 适当性匹配矩阵
  5. 确认摘要生成
  6. 回复格式化
  7. 校验函数 (DB mock)
  8. execute_tool 各分支 (DB mock + API mock)
  9. operator_chat 端到端 (LLM mock)
"""
import asyncio
import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from datetime import datetime, date, time, timedelta
from decimal import Decimal

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agent.operator_agent import (
    _safe_float,
    _check_self_transfer,
    _check_trading_hours,
    _check_suitability,
    _check_holdings,
    _check_balance,
    _check_customer_status,
    _check_risk_assessment_validity,
    _check_daily_cumulative,
    _check_risk_flag,
    _check_pending_risk_alerts,
    _get_customer_risk_level,
    _get_product_risk_level,
    _build_confirmation_summary,
    _format_success_reply,
    check_permission,
    needs_confirmation,
    RBAC_PERMISSIONS,
    CONFIRM_THRESHOLDS,
    execute_tool,
    operator_chat,
)


# ==================== Mock 辅助 ====================

def make_mock_db(rows=None, fetchall=None):
    """构造一个 AsyncMock DB session，支持 execute → mappings().first() / .all()"""
    db = AsyncMock()
    result_mock = MagicMock()
    mappings_mock = MagicMock()

    if fetchall is not None:
        mappings_mock.all.return_value = fetchall
        mappings_mock.first.return_value = fetchall[0] if fetchall else None
    elif rows is not None:
        mappings_mock.first.return_value = rows
        mappings_mock.all.return_value = [rows] if rows else []
    else:
        mappings_mock.first.return_value = None
        mappings_mock.all.return_value = []

    result_mock.mappings.return_value = mappings_mock
    db.execute.return_value = result_mock
    return db


# ==================== 1. 纯函数测试 ====================

class TestSafeFloat:
    def test_normal_float(self):
        v, err = _safe_float(100.5, "金额")
        assert v == 100.5
        assert err is None

    def test_string_number(self):
        v, err = _safe_float("200", "金额")
        assert v == 200.0
        assert err is None

    def test_zero_rejected(self):
        v, err = _safe_float(0, "金额")
        assert v == 0.0
        assert err is not None
        assert "必须大于0" in err

    def test_negative_rejected(self):
        v, err = _safe_float(-10, "金额")
        assert v == 0.0
        assert "必须大于0" in err

    def test_exceeds_limit(self):
        v, err = _safe_float(20_000_000, "金额")
        assert v == 0.0
        assert "超过上限" in err

    def test_invalid_string(self):
        v, err = _safe_float("abc", "金额")
        assert v == 0.0
        assert "格式错误" in err

    def test_none_input(self):
        v, err = _safe_float(None, "金额")
        assert v == 0.0
        assert err is not None

    def test_boundary_limit(self):
        """恰好等于上限 1000万 应通过"""
        v, err = _safe_float(10_000_000, "金额")
        assert v == 10_000_000.0
        assert err is None

    def test_just_over_limit(self):
        """超过上限一分钱"""
        v, err = _safe_float(10_000_000.01, "金额")
        assert v == 0.0
        assert "超过上限" in err


class TestCheckSelfTransfer:
    def test_same_customer_blocked(self):
        err = _check_self_transfer(1, 1)
        assert err is not None
        assert "不能是同一客户" in err

    def test_different_customers_pass(self):
        err = _check_self_transfer(1, 2)
        assert err is None


class TestCheckTradingHours:
    def test_weekend_returns_warning(self):
        """周末应返回警告（非阻断）"""
        # 找一个周末日期来 mock
        mock_now = datetime(2026, 7, 25, 10, 0)  # Saturday
        with patch("app.agent.operator_agent.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _check_trading_hours()
        assert result is not None
        assert "周末" in result or "非交易日" in result

    def test_weekday_trading_hours_pass(self):
        """工作日 9:30-15:00 应通过"""
        mock_now = datetime(2026, 7, 27, 10, 30)  # Monday 10:30
        with patch("app.agent.operator_agent.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _check_trading_hours()
        assert result is None

    def test_before_trading_hours(self):
        """早上 8:00 应返回警告"""
        mock_now = datetime(2026, 7, 27, 8, 0)  # Monday 8:00
        with patch("app.agent.operator_agent.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _check_trading_hours()
        assert result is not None
        assert "非交易时间" in result

    def test_after_trading_hours(self):
        """下午 16:00 应返回警告"""
        mock_now = datetime(2026, 7, 27, 16, 0)
        with patch("app.agent.operator_agent.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _check_trading_hours()
        assert result is not None


# ==================== 2. RBAC 权限矩阵测试 ====================

class TestRBACPermissions:
    def test_admin_has_all_tools(self):
        """管理员应有全部 14 个工具权限"""
        admin_tools = RBAC_PERMISSIONS.get("管理员", [])
        assert len(admin_tools) == 14

    def test_advisor_can_purchase(self):
        err = check_permission("理财顾问", "purchase_product")
        assert err is True

    def test_advisor_cannot_report_suspicious(self):
        """理财顾问不能上报可疑交易"""
        assert check_permission("理财顾问", "report_suspicious") is False

    def test_risk_specialist_can_report(self):
        assert check_permission("风控专员", "report_suspicious") is True

    def test_risk_specialist_cannot_purchase(self):
        assert check_permission("风控专员", "purchase_product") is False

    def test_customer_manager_can_update_contact(self):
        assert check_permission("客户经理", "update_contact") is True

    def test_customer_manager_cannot_purchase(self):
        assert check_permission("客户经理", "purchase_product") is False

    def test_unknown_role_has_no_permission(self):
        assert check_permission("陌生人", "purchase_product") is False

    def test_all_roles_can_query_product(self):
        for role in ["理财顾问", "客户经理", "风控专员", "管理员"]:
            assert check_permission(role, "query_product") is True, f"{role} should be able to query_product"


class TestNeedsConfirmation:
    def test_purchase_above_threshold(self):
        assert needs_confirmation("purchase_product", 50000) is True

    def test_purchase_below_threshold(self):
        assert needs_confirmation("purchase_product", 5000) is False

    def test_purchase_at_threshold(self):
        """恰好等于阈值不触发"""
        assert needs_confirmation("purchase_product", 10000) is False

    def test_transfer_above_threshold(self):
        assert needs_confirmation("transfer_funds", 100000) is True

    def test_transfer_below_threshold(self):
        assert needs_confirmation("transfer_funds", 10000) is False

    def test_query_never_needs_confirmation(self):
        """查询类操作永远不需要确认"""
        assert needs_confirmation("query_product", 99999999) is False
        assert needs_confirmation("query_product_list", 99999999) is False

    def test_redeem_above_threshold(self):
        assert needs_confirmation("redeem_product", 50000) is True

    def test_unknown_action_no_confirmation(self):
        assert needs_confirmation("unknown_action", 99999999) is False


# ==================== 3. 适当性匹配矩阵测试 ====================

class TestSuitabilityMatrix:
    @pytest.mark.asyncio
    async def test_c1_can_buy_r1(self):
        db = make_mock_db()
        # Mock customer risk level = C1
        with patch("app.agent.operator_agent._get_customer_risk_level", return_value="C1"), \
             patch("app.agent.operator_agent._get_product_risk_level", return_value="R1"):
            result = await _check_suitability(1, 1, db)
        assert result is None  # 通过

    @pytest.mark.asyncio
    async def test_c1_cannot_buy_r3(self):
        """保守型客户不能买 R3 产品"""
        db = make_mock_db()
        with patch("app.agent.operator_agent._get_customer_risk_level", return_value="C1"), \
             patch("app.agent.operator_agent._get_product_risk_level", return_value="R3"):
            result = await _check_suitability(1, 1, db)
        assert result is not None
        assert "适当性不匹配" in result

    @pytest.mark.asyncio
    async def test_c5_can_buy_any(self):
        """激进型客户可以买所有级别"""
        db = make_mock_db()
        with patch("app.agent.operator_agent._get_customer_risk_level", return_value="C5"):
            for product_level in ["R1", "R2", "R3", "R4", "R5"]:
                with patch("app.agent.operator_agent._get_product_risk_level", return_value=product_level):
                    result = await _check_suitability(1, 1, db)
                    assert result is None, f"C5 should be able to buy {product_level}"

    @pytest.mark.asyncio
    async def test_no_assessment_blocks(self):
        """未做风评的客户被阻断"""
        db = make_mock_db()
        with patch("app.agent.operator_agent._get_customer_risk_level", return_value=None):
            result = await _check_suitability(1, 1, db)
        assert result is not None
        assert "风险评估" in result

    @pytest.mark.asyncio
    async def test_chinese_risk_level(self):
        """中文风险等级 '保守型' 应该映射到 C1"""
        db = make_mock_db()
        with patch("app.agent.operator_agent._get_customer_risk_level", return_value="保守型"), \
             patch("app.agent.operator_agent._get_product_risk_level", return_value="R1"):
            result = await _check_suitability(1, 1, db)
        assert result is None


# ==================== 4. DB 校验函数测试 ====================

class TestCheckCustomerStatus:
    @pytest.mark.asyncio
    async def test_normal_status_pass(self):
        db = make_mock_db(rows={"status": "正常"})
        result = await _check_customer_status(1, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_frozen_status_blocked(self):
        db = make_mock_db(rows={"status": "冻结"})
        result = await _check_customer_status(1, db)
        assert result is not None
        assert "状态异常" in result

    @pytest.mark.asyncio
    async def test_customer_not_found(self):
        db = make_mock_db(rows=None)
        result = await _check_customer_status(999, db)
        assert result is not None
        assert "未找到" in result


class TestCheckHoldings:
    @pytest.mark.asyncio
    async def test_sufficient_holdings(self):
        db = make_mock_db(rows={"shares": Decimal("1000")})
        result = await _check_holdings(1, 1, 500.0, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_insufficient_holdings(self):
        db = make_mock_db(rows={"shares": Decimal("100")})
        result = await _check_holdings(1, 1, 500.0, db)
        assert result is not None
        assert "超过持有份额" in result

    @pytest.mark.asyncio
    async def test_no_holdings(self):
        db = make_mock_db(rows=None)
        result = await _check_holdings(1, 1, 500.0, db)
        assert result is not None
        assert "未持有" in result


class TestCheckBalance:
    @pytest.mark.asyncio
    async def test_sufficient_balance(self):
        db = make_mock_db(rows={"balance": Decimal("100000")})
        result = await _check_balance(1, 50000.0, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_insufficient_balance(self):
        db = make_mock_db(rows={"balance": Decimal("1000")})
        result = await _check_balance(1, 50000.0, db)
        assert result is not None
        assert "余额不足" in result

    @pytest.mark.asyncio
    async def test_account_not_found(self):
        db = make_mock_db(rows=None)
        result = await _check_balance(999, 50000.0, db)
        assert result is not None
        assert "未找到" in result


class TestCheckRiskAssessmentValidity:
    @pytest.mark.asyncio
    async def test_valid_assessment_pass(self):
        future_date = (datetime.now() + timedelta(days=365)).date()
        db = make_mock_db(rows={"risk_level": "C3", "valid_until": future_date})
        result = await _check_risk_assessment_validity(1, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_assessment_blocked(self):
        past_date = (datetime.now() - timedelta(days=30)).date()
        db = make_mock_db(rows={"risk_level": "C3", "valid_until": past_date})
        result = await _check_risk_assessment_validity(1, db)
        assert result is not None
        assert "已过期" in result

    @pytest.mark.asyncio
    async def test_no_assessment_blocked(self):
        db = make_mock_db(rows=None)
        result = await _check_risk_assessment_validity(1, db)
        assert result is not None
        assert "风险评估" in result


class TestCheckDailyCumulative:
    @pytest.mark.asyncio
    async def test_below_limit(self):
        db = make_mock_db(rows={"total": 500000.0})
        result = await _check_daily_cumulative(1, 100000.0, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_exceeds_limit(self):
        db = make_mock_db(rows={"total": 1900000.0})
        result = await _check_daily_cumulative(1, 200000.0, db)
        assert result is not None
        assert "累计限额" in result

    @pytest.mark.asyncio
    async def test_no_previous_transactions(self):
        db = make_mock_db(rows={"total": 0})
        result = await _check_daily_cumulative(1, 100000.0, db)
        assert result is None


class TestCheckRiskFlag:
    @pytest.mark.asyncio
    async def test_normal_flag_pass(self):
        db = make_mock_db(rows={"risk_flag": "normal"})
        result = await _check_risk_flag(1, db, "客户")
        assert result is None

    @pytest.mark.asyncio
    async def test_high_flag_warning(self):
        db = make_mock_db(rows={"risk_flag": "high"})
        result = await _check_risk_flag(1, db, "客户")
        assert result is not None
        assert "高风险" in result

    @pytest.mark.asyncio
    async def test_warning_flag_warning(self):
        db = make_mock_db(rows={"risk_flag": "warning"})
        result = await _check_risk_flag(1, db, "转出方")
        assert result is not None
        assert "风险预警" in result
        assert "转出方" in result

    @pytest.mark.asyncio
    async def test_no_profile_pass(self):
        db = make_mock_db(rows=None)
        result = await _check_risk_flag(1, db, "客户")
        assert result is None


class TestCheckPendingRiskAlerts:
    @pytest.mark.asyncio
    async def test_no_alerts_pass(self):
        db = make_mock_db(rows={"cnt": 0, "max_level": None})
        result = await _check_pending_risk_alerts(1, db, "客户")
        assert result is None

    @pytest.mark.asyncio
    async def test_pending_alerts_warning(self):
        db = make_mock_db(rows={"cnt": 3, "max_level": "high"})
        result = await _check_pending_risk_alerts(1, db, "客户")
        assert result is not None
        assert "3 条" in result
        assert "high" in result

    @pytest.mark.asyncio
    async def test_medium_alerts(self):
        db = make_mock_db(rows={"cnt": 1, "max_level": "medium"})
        result = await _check_pending_risk_alerts(1, db, "转入方")
        assert result is not None
        assert "转入方" in result


# ==================== 5. 确认摘要生成测试 ====================

class TestBuildConfirmationSummary:
    def test_purchase_summary(self):
        summary = _build_confirmation_summary("purchase_product", {
            "customer_name": "张三",
            "product_name": "天弘稳健",
            "amount": 50000,
        })
        assert "张三" in summary
        assert "天弘稳健" in summary
        assert "50000" in summary

    def test_redeem_summary(self):
        summary = _build_confirmation_summary("redeem_product", {
            "customer_name": "李四",
            "product_name": "华夏成长",
            "shares": 1000,
        })
        assert "李四" in summary
        assert "华夏成长" in summary

    def test_transfer_summary(self):
        summary = _build_confirmation_summary("transfer_funds", {
            "from_customer_name": "张三",
            "to_customer_name": "李四",
            "amount": 100000,
        })
        assert "张三" in summary
        assert "李四" in summary
        assert "100000" in summary

    def test_unknown_action_summary(self):
        summary = _build_confirmation_summary("unknown_action", {"key": "val"})
        assert "unknown_action" in summary


# ==================== 6. 回复格式化测试 ====================

class TestFormatSuccessReply:
    def test_purchase_reply(self):
        reply = _format_success_reply("purchase_product", {}, {
            "transaction_no": "TX001",
            "product_name": "天弘稳健",
            "amount": 50000,
            "shares": 5000,
            "nav_date": "2026-07-24",
        })
        assert "申购成功" in reply
        assert "TX001" in reply

    def test_redeem_reply(self):
        reply = _format_success_reply("redeem_product", {}, {
            "transaction_no": "TX002",
            "shares": 1000,
            "amount": 10500,
        })
        assert "赎回成功" in reply

    def test_transfer_reply(self):
        reply = _format_success_reply("transfer_funds", {}, {
            "transaction_no": "TX003",
            "amount": 100000,
            "to_customer_id": 5,
        })
        assert "转账成功" in reply

    def test_query_product_reply(self):
        reply = _format_success_reply("query_product", {}, {
            "product_name": "天弘稳健",
            "product_code": "TH001",
            "product_type": "债券型",
            "risk_level": "R2",
            "expected_return": 4.5,
            "min_amount": 1000,
            "fund_manager": "张三",
        })
        assert "天弘稳健" in reply
        assert "R2" in reply

    def test_unknown_action_reply(self):
        reply = _format_success_reply("unknown_action", {}, {})
        assert "执行成功" in reply


# ==================== 7. execute_tool 分支测试（mock） ====================

class TestExecuteTool:
    @pytest.mark.asyncio
    async def test_purchase_customer_not_found(self):
        with patch("app.agent.operator_agent.resolve_customer_id", return_value=None):
            result = await execute_tool("purchase_product", {
                "customer_name": "不存在",
                "product_name": "产品A",
                "amount": 10000,
            }, operator_id=1)
        assert result["success"] is False
        assert "未找到客户" in result["message"]

    @pytest.mark.asyncio
    async def test_purchase_product_not_found(self):
        with patch("app.agent.operator_agent.resolve_customer_id", return_value=1), \
             patch("app.agent.operator_agent.resolve_product_id", return_value=None):
            result = await execute_tool("purchase_product", {
                "customer_name": "张三",
                "product_name": "不存在",
                "amount": 10000,
            }, operator_id=1)
        assert result["success"] is False
        assert "未找到产品" in result["message"]

    @pytest.mark.asyncio
    async def test_purchase_invalid_amount(self):
        result = await execute_tool("purchase_product", {
            "customer_name": "张三",
            "product_name": "产品A",
            "amount": -100,
        }, operator_id=1)
        assert result["success"] is False
        assert "必须大于0" in result["message"]

    @pytest.mark.asyncio
    async def test_purchase_customer_frozen(self):
        """客户冻结时应阻断申购"""
        mock_db = make_mock_db(rows={"status": "冻结"})
        with patch("app.agent.operator_agent.resolve_customer_id", return_value=1), \
             patch("app.agent.operator_agent.resolve_product_id", return_value=1), \
             patch("app.config.database.async_session_factory") as mock_factory:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_db
            mock_ctx.__aexit__.return_value = None
            mock_factory.return_value = mock_ctx

            result = await execute_tool("purchase_product", {
                "customer_name": "张三",
                "product_name": "产品A",
                "amount": 10000,
            }, operator_id=1)
        assert result["success"] is False
        assert "状态异常" in result["message"] or "冻结" in result["message"]

    @pytest.mark.asyncio
    async def test_transfer_self_transfer_blocked(self):
        """自转账应被阻断"""
        with patch("app.agent.operator_agent.resolve_customer_id", side_effect=[1, 1]):
            result = await execute_tool("transfer_funds", {
                "from_customer_name": "张三",
                "to_customer_name": "张三",
                "amount": 10000,
            }, operator_id=1)
        assert result["success"] is False
        assert "不能是同一客户" in result["message"]

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        result = await execute_tool("nonexistent_tool", {})
        assert result["success"] is False
        assert "未知工具" in result["message"]

    @pytest.mark.asyncio
    async def test_redeem_no_holdings(self):
        """赎回时未持有产品应阻断"""
        mock_db_no_holdings = make_mock_db(rows=None)  # holdings returns None

        call_count = 0
        async def mock_check_holdings(cid, pid, shares, db):
            return "客户未持有该产品，无法赎回"

        with patch("app.agent.operator_agent.resolve_customer_id", return_value=1), \
             patch("app.agent.operator_agent.resolve_product_id", return_value=1), \
             patch("app.agent.operator_agent._check_customer_status", return_value=None), \
             patch("app.agent.operator_agent._check_holdings", return_value="客户未持有该产品，无法赎回"):
            result = await execute_tool("redeem_product", {
                "customer_name": "张三",
                "product_name": "产品A",
                "shares": 100,
            }, operator_id=1)
        assert result["success"] is False
        assert "未持有" in result["message"]


# ==================== 8. operator_chat 端到端测试（LLM mock） ====================

class TestOperatorChat:
    @pytest.mark.asyncio
    async def test_unknown_role_blocked(self):
        """无权限角色应被直接拒绝，不调用 LLM"""
        mock_memory = AsyncMock()
        mock_memory.get_messages.return_value = []
        with patch("app.agent.operator_agent.SessionMemory", return_value=mock_memory), \
             patch("app.agent.operator_agent.llm_client") as mock_llm:
            mock_llm.chat.completions.create = AsyncMock()
            result = await operator_chat(
                message="帮我申购10000元天弘稳健",
                session_id="test-session-1",
                user_id=1,
                user_role="未知角色",
            )
        mock_llm.chat.completions.create.assert_not_called()
        assert result["status"] == "permission_denied"
        assert "权限" in result["reply"]

    @pytest.mark.asyncio
    async def test_cancel_without_pending_goes_to_llm(self):
        """没有待确认操作时，用户说'取消'应该 fall through 到 LLM（不作为关键字拦截）"""
        mock_memory = AsyncMock()
        mock_memory.get_messages.return_value = []
        mock_resp = MagicMock()
        mock_msg = MagicMock()
        mock_msg.tool_calls = None
        mock_msg.content = "好的，已为您取消操作。"
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message = mock_msg

        with patch("app.agent.operator_agent.SessionMemory", return_value=mock_memory), \
             patch("app.agent.operator_agent._load_pending_confirm", return_value=None), \
             patch("app.agent.operator_agent.llm_client") as mock_llm:
            mock_llm.chat.completions.create = AsyncMock(return_value=mock_resp)
            result = await operator_chat(
                message="取消",
                session_id="test-session-2",
                user_id=1,
                user_role="理财顾问",
            )
        # 没有待确认时，"取消" fall through 到 LLM
        assert result["status"] == "ok"
        assert mock_llm.chat.completions.create.called

    @pytest.mark.asyncio
    async def test_cancel_with_pending(self):
        """有待确认操作时，用户说'取消'应直接取消并返回"""
        mock_memory = AsyncMock()
        mock_memory.get_messages.return_value = []
        pending_data = {
            "action": "purchase_product",
            "arguments": {"customer_name": "张三", "product_name": "产品A", "amount": 50000},
            "user_id": 1,
            "user_role": "理财顾问",
            "summary": "申购：张三 购买 产品A，金额 50000 元",
        }
        with patch("app.agent.operator_agent.SessionMemory", return_value=mock_memory), \
             patch("app.agent.operator_agent._load_pending_confirm", return_value=pending_data), \
             patch("app.agent.operator_agent._delete_pending_confirm", new=AsyncMock()), \
             patch("app.agent.operator_agent.llm_client") as mock_llm:
            mock_llm.chat.completions.create = AsyncMock()
            result = await operator_chat(
                message="取消",
                session_id="test-session-cancel",
                user_id=1,
                user_role="理财顾问",
            )
        # 不调用 LLM，直接取消
        mock_llm.chat.completions.create.assert_not_called()
        assert result["status"] == "cancelled"
        assert "取消" in result["reply"]



    @pytest.mark.asyncio
    async def test_confirm_with_pending_executes(self):
        """有待确认操作时，用户说'确认'应执行操作"""
        mock_memory = AsyncMock()
        mock_memory.get_messages.return_value = []
        pending_data = {
            "action": "purchase_product",
            "arguments": {"customer_name": "张三", "product_name": "产品A", "amount": 50000},
            "user_id": 1,
            "user_role": "理财顾问",
            "summary": "申购：张三 购买 产品A，金额 50000 元",
        }
        mock_result = {"success": True, "data": {"transaction_no": "TX001", "amount": 50000,
                                                     "product_name": "产品A", "shares": 5000, "nav_date": "2026-07-24"}}
        with patch("app.agent.operator_agent.SessionMemory", return_value=mock_memory),              patch("app.agent.operator_agent._load_pending_confirm", return_value=pending_data),              patch("app.agent.operator_agent._delete_pending_confirm", new=AsyncMock()),              patch("app.agent.operator_agent.execute_tool", new=AsyncMock(return_value=mock_result)),              patch("app.agent.operator_agent._archive_memory", new=AsyncMock()),              patch("app.agent.operator_agent.llm_client") as mock_llm:
            mock_llm.chat.completions.create = AsyncMock()
            result = await operator_chat(
                message="确认",
                session_id="test-session-confirm",
                user_id=1,
                user_role="理财顾问",
            )
        mock_llm.chat.completions.create.assert_not_called()
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_purchase_suitability_mismatch(self):
        """申购时适当性不匹配应阻断"""
        with patch("app.agent.operator_agent.resolve_customer_id", return_value=1),              patch("app.agent.operator_agent.resolve_product_id", return_value=1),              patch("app.agent.operator_agent._check_customer_status", return_value=None),              patch("app.agent.operator_agent._check_suitability", return_value="⚠️ 适当性不匹配"):
            result = await execute_tool("purchase_product", {
                "customer_name": "张三",
                "product_name": "高风险产品",
                "amount": 10000,
            })
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_purchase_expired_risk_assessment(self):
        """申购时风评过期应阻断"""
        with patch("app.agent.operator_agent.resolve_customer_id", return_value=1),              patch("app.agent.operator_agent.resolve_product_id", return_value=1),              patch("app.agent.operator_agent._check_customer_status", return_value=None),              patch("app.agent.operator_agent._check_suitability", return_value=None),              patch("app.agent.operator_agent._check_risk_assessment_validity", return_value="⚠️ 客户风险评估已过期"):
            result = await execute_tool("purchase_product", {
                "customer_name": "张三",
                "product_name": "产品A",
                "amount": 10000,
            })
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_transfer_both_parties_risk_check(self):
        """转账时转出方和转入方都应进行风控检查"""
        async def mock_check_risk_flag(cid, db, label="客户"):
            if cid == 1:
                return "⚠️ 转出方被标记为【高风险】"
            if cid == 2:
                return "⚠️ 转入方存在【风险预警】"
            return None

        mock_db = make_mock_db()
        mock_api_result = MagicMock()
        mock_api_result.code = 200
        mock_api_result.message = "转账成功"
        mock_api_result.data = {"transaction_no": "TX001", "amount": 5000, "to_customer_id": 2}

        with patch("app.agent.operator_agent.resolve_customer_id", side_effect=[1, 2]),              patch("app.agent.operator_agent._check_customer_status", return_value=None),              patch("app.agent.operator_agent._check_balance", return_value=None),              patch("app.agent.operator_agent._check_daily_cumulative", return_value=None),              patch("app.agent.operator_agent._check_risk_flag", side_effect=mock_check_risk_flag),              patch("app.agent.operator_agent._check_pending_risk_alerts", return_value=None),              patch("app.agent.operator_agent._check_trading_hours", return_value=None),              patch("app.agent.operator_agent._check_transfer_eligibility", return_value=None),              patch("app.agent.operator_agent.transfer_funds", new=AsyncMock(return_value=mock_api_result)),              patch("app.config.database.async_session_factory") as mock_factory:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_db
            mock_ctx.__aexit__.return_value = None
            mock_factory.return_value = mock_ctx

            result = await execute_tool("transfer_funds", {
                "from_customer_name": "张三",
                "to_customer_name": "李四",
                "amount": 5000,
            }, operator_id=1)

        assert result["success"] is True
        assert result["message"].count("⚠️") >= 2  # 转出方 + 转入方 都有警告

# ==================== 9. 边界条件测试 ====================

class TestEdgeCases:
    def test_rbac_all_actions_valid(self):
        """RBAC 中所有 action 必须在 TOOLS 中有对应定义"""
        from app.agent.operator_agent import TOOLS
        tool_names = {t["function"]["name"] for t in TOOLS}
        for role, actions in RBAC_PERMISSIONS.items():
            for action in actions:
                assert action in tool_names, f"RBAC '{role}' has '{action}' but it's not in TOOLS"

    def test_confirm_thresholds_match_tools(self):
        """确认阈值的 action 必须在 TOOLS 中存在"""
        from app.agent.operator_agent import TOOLS
        tool_names = {t["function"]["name"] for t in TOOLS}
        for action in CONFIRM_THRESHOLDS:
            assert action in tool_names, f"CONFIRM_THRESHOLDS has '{action}' but not in TOOLS"

    def test_suitability_map_complete(self):
        """适当性矩阵应覆盖 C1-C5"""
        from app.agent.operator_agent import _SUITABILITY_MAP
        for level in ["C1", "C2", "C3", "C4", "C5"]:
            assert level in _SUITABILITY_MAP, f"_SUITABILITY_MAP missing {level}"

    def test_risk_level_normalize_complete(self):
        """风险等级映射应完整（中文 + R1-R5 都能映射到 C1-C5）"""
        from app.agent.operator_agent import _RISK_LEVEL_NORMALIZE
        # Chinese names
        for name in ["保守型", "稳健型", "平衡型", "进取型", "激进型"]:
            assert name in _RISK_LEVEL_NORMALIZE, f"_RISK_LEVEL_NORMALIZE missing '{name}'"
        # R-levels
        for level in ["R1", "R2", "R3", "R4", "R5"]:
            assert level in _RISK_LEVEL_NORMALIZE, f"_RISK_LEVEL_NORMALIZE missing '{level}'"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
