"""
P4 新增校验测试：产品状态 / 赎回次数 / 联系方式格式 / 最低保留份额 / 大额备注
"""
import asyncio
import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, date, time, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agent.operator_agent import (
    _check_product_status,
    _check_daily_redeem_count,
    _check_contact_format,
    _check_transfer_eligibility,
    _check_min_remaining_shares,
    _build_confirmation_summary,
    execute_tool,
)


# ==================== Mock 辅助 ====================

def make_mock_db(rows=None, fetchall=None):
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


# ==================== 10. P4 新增校验测试 ====================

class TestProductStatusCheck:
    @pytest.mark.asyncio
    async def test_on_sale_pass(self):
        """在售产品可以申购"""
        db = make_mock_db(rows={"status": "on_sale", "product_name": "天弘稳健"})
        result = await _check_product_status(1, "purchase", db)
        assert result is None

    @pytest.mark.asyncio
    async def test_off_sale_blocked(self):
        """已下架产品不能申购"""
        db = make_mock_db(rows={"status": "off_sale", "product_name": "天弘稳健"})
        result = await _check_product_status(1, "purchase", db)
        assert result is not None
        assert "下架" in result

    @pytest.mark.asyncio
    async def test_suspended_blocked(self):
        """暂停申购产品不能申购"""
        db = make_mock_db(rows={"status": "suspended", "product_name": "天弘稳健"})
        result = await _check_product_status(1, "purchase", db)
        assert result is not None
        assert "暂停" in result

    @pytest.mark.asyncio
    async def test_terminated_redeem_blocked(self):
        """已终止产品不能赎回"""
        db = make_mock_db(rows={"status": "terminated", "product_name": "天弘稳健"})
        result = await _check_product_status(1, "redeem", db)
        assert result is not None
        assert "终止" in result

    @pytest.mark.asyncio
    async def test_liquidating_redeem_blocked(self):
        """清算中产品不能赎回"""
        db = make_mock_db(rows={"status": "liquidating", "product_name": "天弘稳健"})
        result = await _check_product_status(1, "redeem", db)
        assert result is not None
        assert "清算" in result

    @pytest.mark.asyncio
    async def test_off_sale_can_redeem(self):
        """已下架产品可以赎回（不在赎回阻断列表中）"""
        db = make_mock_db(rows={"status": "off_sale", "product_name": "天弘稳健"})
        result = await _check_product_status(1, "redeem", db)
        assert result is None


class TestDailyRedeemCount:
    @pytest.mark.asyncio
    async def test_below_limit(self):
        db = make_mock_db(rows={"cnt": 2})
        result = await _check_daily_redeem_count(1, 1, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_at_limit(self):
        db = make_mock_db(rows={"cnt": 3})
        result = await _check_daily_redeem_count(1, 1, db)
        assert result is not None
        assert "3 次" in result

    @pytest.mark.asyncio
    async def test_no_previous(self):
        db = make_mock_db(rows={"cnt": 0})
        result = await _check_daily_redeem_count(1, 1, db)
        assert result is None


class TestContactFormat:
    def test_valid_phone(self):
        result = _check_contact_format("phone", "13900001234")
        assert result is None

    def test_invalid_phone_short(self):
        result = _check_contact_format("phone", "1390000123")
        assert result is not None
        assert "格式错误" in result

    def test_invalid_phone_prefix(self):
        result = _check_contact_format("phone", "23900001234")
        assert result is not None
        assert "格式错误" in result

    def test_valid_email(self):
        result = _check_contact_format("email", "test@example.com")
        assert result is None

    def test_invalid_email(self):
        result = _check_contact_format("email", "not-an-email")
        assert result is not None
        assert "格式错误" in result

    def test_empty_value(self):
        result = _check_contact_format("phone", "")
        assert result is not None
        assert "不能为空" in result

    def test_unknown_field_passes(self):
        result = _check_contact_format("address", "上海市")
        assert result is None


class TestMinRemainingShares:
    @pytest.mark.asyncio
    async def test_sufficient_remaining(self):
        """赎回后剩余份额充足，通过"""
        db = make_mock_db(rows={"shares": Decimal("10000")})
        result = await _check_min_remaining_shares(1, 1, 500.0, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_below_min_remaining(self):
        """赎回后剩余 50 份，低于 100 份最低持有，提示"""
        db = make_mock_db(rows={"shares": Decimal("550")})
        result = await _check_min_remaining_shares(1, 1, 500.0, db)
        assert result is not None
        assert "50" in result
        assert "全部赎回" in result

    @pytest.mark.asyncio
    async def test_full_redeem_pass(self):
        """全部赎回（剩余 0），应通过"""
        db = make_mock_db(rows={"shares": Decimal("500")})
        result = await _check_min_remaining_shares(1, 1, 500.0, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_holdings_pass(self):
        """无持仓，让下游处理"""
        db = make_mock_db(rows=None)
        result = await _check_min_remaining_shares(1, 1, 500.0, db)
        assert result is None


class TestLargeAmountNote:
    def test_purchase_large_amount_note(self):
        """申购 50万以上应附加备注提示"""
        summary = _build_confirmation_summary("purchase_product", {
            "customer_name": "张三", "product_name": "产品A", "amount": 600000,
        })
        assert "备注" in summary

    def test_purchase_small_amount_no_note(self):
        """申购 1万以下不需备注提示"""
        summary = _build_confirmation_summary("purchase_product", {
            "customer_name": "张三", "product_name": "产品A", "amount": 10000,
        })
        assert "备注" not in summary

    def test_transfer_large_amount_note(self):
        """转账 50万以上应附加备注提示"""
        summary = _build_confirmation_summary("transfer_funds", {
            "from_customer_name": "张三", "to_customer_name": "李四", "amount": 1000000,
        })
        assert "备注" in summary

    def test_at_threshold(self):
        """恰好 50万，应附加备注提示"""
        summary = _build_confirmation_summary("purchase_product", {
            "customer_name": "张三", "product_name": "产品A", "amount": 500000,
        })
        assert "备注" in summary

    def test_just_below_threshold(self):
        """49.99万，不需备注"""
        summary = _build_confirmation_summary("purchase_product", {
            "customer_name": "张三", "product_name": "产品A", "amount": 499999,
        })
        assert "备注" not in summary


class TestP4Integration:
    @pytest.mark.asyncio
    async def test_update_contact_invalid_phone(self):
        """update_contact 校验无效手机号应阻断"""
        with patch("app.agent.operator_agent.resolve_customer_id", return_value=1), \
             patch("app.agent.operator_agent._check_contact_format", return_value="手机号格式错误"):
            result = await execute_tool("update_contact", {
                "customer_name": "张三",
                "field": "phone",
                "value": "123",
            }, operator_id=1)
        assert result["success"] is False
        assert "格式错误" in result["message"]

    @pytest.mark.asyncio
    async def test_purchase_product_off_sale_blocked(self):
        """申购已下架产品应阻断"""
        with patch("app.agent.operator_agent.resolve_customer_id", return_value=1), \
             patch("app.agent.operator_agent.resolve_product_id", return_value=1), \
             patch("app.agent.operator_agent._check_purchase_amount_multiple", return_value=None), \
             patch("app.agent.operator_agent._check_product_min_purchase_amount", return_value=None), \
             patch("app.agent.operator_agent._check_product_raise_quota", return_value=None), \
             patch("app.agent.operator_agent._check_product_status", return_value="产品已下架"):
            result = await execute_tool("purchase_product", {
                "customer_name": "张三",
                "product_name": "产品A",
                "amount": 10000,
            }, operator_id=1)
        assert result["success"] is False
        assert "下架" in result["message"]

    @pytest.mark.asyncio
    async def test_redeem_daily_limit_blocked(self):
        """赎回达到单日次数上限应阻断"""
        with patch("app.agent.operator_agent.resolve_customer_id", return_value=1), \
             patch("app.agent.operator_agent.resolve_product_id", return_value=1), \
             patch("app.agent.operator_agent._check_redeem_shares_precision", return_value=None), \
             patch("app.agent.operator_agent._check_customer_status", return_value=None), \
             patch("app.agent.operator_agent._check_product_status", return_value=None), \
             patch("app.agent.operator_agent._check_holdings", return_value=None), \
             patch("app.agent.operator_agent._check_daily_redeem_count", return_value="今日已赎回 3 次"):
            result = await execute_tool("redeem_product", {
                "customer_name": "张三",
                "product_name": "产品A",
                "shares": 100,
            }, operator_id=1)
        assert result["success"] is False
        assert "3 次" in result["message"]

    @pytest.mark.asyncio
    async def test_redeem_min_shares_warning(self):
        """赎回后剩余份额低于最低，应附加警告但不阻断"""
        mock_db = make_mock_db()
        mock_api_result = MagicMock()
        mock_api_result.code = 200
        mock_api_result.message = "赎回成功"
        mock_api_result.data = {"transaction_no": "TX001", "shares": 450, "amount": 4725}

        with patch("app.agent.operator_agent.resolve_customer_id", return_value=1), \
             patch("app.agent.operator_agent.resolve_product_id", return_value=1), \
             patch("app.agent.operator_agent._check_redeem_shares_precision", return_value=None), \
             patch("app.agent.operator_agent._check_customer_status", return_value=None), \
             patch("app.agent.operator_agent._check_product_status", return_value=None), \
             patch("app.agent.operator_agent._check_holdings", return_value=None), \
             patch("app.agent.operator_agent._check_daily_redeem_count", return_value=None), \
             patch("app.agent.operator_agent._check_min_remaining_shares", return_value="⚠️ 赎回后剩余50份，低于最低持有要求100份"), \
             patch("app.agent.operator_agent._check_risk_flag", return_value=None), \
             patch("app.agent.operator_agent._check_pending_risk_alerts", return_value=None), \
             patch("app.agent.operator_agent._check_trading_hours", return_value=None), \
             patch("app.agent.operator_agent.redeem_product", new=AsyncMock(return_value=mock_api_result)), \
             patch("app.config.database.async_session_factory") as mock_factory:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_db
            mock_ctx.__aexit__.return_value = None
            mock_factory.return_value = mock_ctx

            result = await execute_tool("redeem_product", {
                "customer_name": "张三",
                "product_name": "产品A",
                "shares": 450,
            }, operator_id=1)

        assert result["success"] is True
        assert "最低持有" in result["message"]
