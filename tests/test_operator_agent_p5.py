"""
P5 新增校验测试：产品起购金额 / 申购整数倍 / 赎回精度 / 产品额度 / 转账最低 / 防重复上报
"""
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.agent.operator_agent import (
    _check_purchase_amount_multiple,
    _check_min_transfer_amount,
    _check_product_min_purchase_amount,
    _check_product_raise_quota,
    _check_redeem_shares_precision,
    _check_suspicious_repeat,
    _PURCHASE_AMOUNT_MULTIPLE,
    _MIN_TRANSFER_AMOUNT,
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


# ==================== 申购金额整数倍校验 ====================

class TestPurchaseAmountMultiple:
    def test_valid_100(self):
        """100 元（100 的 1 倍）通过"""
        assert _check_purchase_amount_multiple(100) is None

    def test_valid_10000(self):
        """10000 元通过"""
        assert _check_purchase_amount_multiple(10000) is None

    def test_invalid_50(self):
        """50 元（不足 100 的倍数）应报错"""
        result = _check_purchase_amount_multiple(50)
        assert result is not None
        assert "整数倍" in result

    def test_invalid_150(self):
        """150 元不是 100 的整数倍"""
        result = _check_purchase_amount_multiple(150)
        assert result is not None
        assert "100" in result

    def test_invalid_12345(self):
        """12345 元不是 100 的整数倍"""
        result = _check_purchase_amount_multiple(12345)
        assert result is not None

    def test_zero_pass(self):
        """0 元交给 _safe_float 处理，此处不报错"""
        assert _check_purchase_amount_multiple(0) is None

    def test_negative_pass(self):
        """负数交给 _safe_float 处理"""
        assert _check_purchase_amount_multiple(-100) is None


# ==================== 转账最低金额校验 ====================

class TestMinTransferAmount:
    def test_below_min(self):
        """99 元低于最低 100 元"""
        result = _check_min_transfer_amount(99)
        assert result is not None
        assert str(_MIN_TRANSFER_AMOUNT) in result

    def test_at_min(self):
        """恰好 100 元通过"""
        assert _check_min_transfer_amount(100) is None

    def test_above_min(self):
        """1000 元通过"""
        assert _check_min_transfer_amount(1000) is None

    def test_tiny_amount(self):
        """0.01 元报错"""
        result = _check_min_transfer_amount(0.01)
        assert result is not None


# ==================== 赎回份额精度校验 ====================

class TestRedeemSharesPrecision:
    def test_integer_pass(self):
        """整数份额通过"""
        assert _check_redeem_shares_precision(100) is None

    def test_two_decimals_pass(self):
        """2 位小数通过（如 100.50）"""
        assert _check_redeem_shares_precision(100.50) is None

    def test_three_decimals_fail(self):
        """3 位小数报错"""
        result = _check_redeem_shares_precision(100.123)
        assert result is not None
        assert "精度" in result or "小数" in result

    def test_four_decimals_fail(self):
        """4 位小数报错"""
        result = _check_redeem_shares_precision(100.1234)
        assert result is not None

    def test_zero_pass(self):
        """0 交给 _safe_float 处理"""
        assert _check_redeem_shares_precision(0) is None


# ==================== 产品最低起购金额校验 ====================

class TestProductMinPurchaseAmount:
    @pytest.mark.asyncio
    async def test_amount_meets_minimum(self):
        """申购金额 >= 产品最低起购金额，通过"""
        db = make_mock_db(rows={"min_purchase_amount": 1000, "product_name": "稳健增长A"})
        result = await _check_product_min_purchase_amount(1, 5000, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_amount_below_minimum(self):
        """申购金额 < 产品最低起购金额，报错"""
        db = make_mock_db(rows={"min_purchase_amount": 1000, "product_name": "稳健增长A"})
        result = await _check_product_min_purchase_amount(1, 500, db)
        assert result is not None
        assert "1000" in result
        assert "稳健增长A" in result

    @pytest.mark.asyncio
    async def test_amount_equal_minimum(self):
        """恰好等于最低起购金额，通过"""
        db = make_mock_db(rows={"min_purchase_amount": 1000, "product_name": "产品X"})
        result = await _check_product_min_purchase_amount(1, 1000, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_minimum_configured(self):
        """产品未配置最低起购金额，跳过校验"""
        db = make_mock_db(rows={"min_purchase_amount": None, "product_name": "产品Y"})
        result = await _check_product_min_purchase_amount(1, 10, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_product_not_found(self):
        """产品不存在，让下游处理"""
        db = make_mock_db(rows=None)
        result = await _check_product_min_purchase_amount(1, 1000, db)
        assert result is None


# ==================== 产品剩余额度校验 ====================

class TestProductRaiseQuota:
    @pytest.mark.asyncio
    async def test_quota_sufficient(self):
        """剩余额度充足，通过"""
        db = make_mock_db(rows={
            "max_raise_amount": 10000000,  # 1000 万
            "raised_amount": 5000000,      # 已募 500 万
            "product_name": "创新增长",
        })
        result = await _check_product_raise_quota(1, 10000, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_quota_insufficient(self):
        """剩余额度不足，报错"""
        db = make_mock_db(rows={
            "max_raise_amount": 10000000,  # 1000 万
            "raised_amount": 9990000,      # 已募 999 万
            "product_name": "创新增长",
        })
        result = await _check_product_raise_quota(1, 100000, db)  # 申购 10 万
        assert result is not None
        assert "额度不足" in result
        assert "创新增长" in result

    @pytest.mark.asyncio
    async def test_no_max_raise(self):
        """未设置规模上限，跳过"""
        db = make_mock_db(rows={
            "max_raise_amount": None,
            "raised_amount": 5000000,
            "product_name": "产品Z",
        })
        result = await _check_product_raise_quota(1, 100000, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_zero_max_raise(self):
        """max_raise_amount 为 0 视为未设置上限"""
        db = make_mock_db(rows={
            "max_raise_amount": 0,
            "raised_amount": 0,
            "product_name": "产品W",
        })
        result = await _check_product_raise_quota(1, 100000, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_product_not_found(self):
        """产品不存在，让下游处理"""
        db = make_mock_db(rows=None)
        result = await _check_product_raise_quota(1, 100000, db)
        assert result is None


# ==================== 可疑交易防重复上报 ====================

class TestSuspiciousRepeat:
    @pytest.mark.asyncio
    async def test_no_previous_reports(self):
        """客户无历史举报，通过"""
        db = make_mock_db(fetchall=[])
        result = await _check_suspicious_repeat(1, "客户频繁大额转账", db)
        assert result is None

    @pytest.mark.asyncio
    async def test_different_reason(self):
        """历史举报原因不同，通过"""
        db = make_mock_db(fetchall=[
            {"reason": "客户异地登录", "create_time": None},
        ])
        result = await _check_suspicious_repeat(1, "客户频繁大额转账", db)
        assert result is None

    @pytest.mark.asyncio
    async def test_same_reason_repeat(self):
        """相同原因重复举报，提示"""
        from datetime import datetime
        db = make_mock_db(fetchall=[
            {"reason": "客户频繁大额转账", "create_time": datetime(2026, 7, 24, 10, 0)},
        ])
        result = await _check_suspicious_repeat(1, "客户频繁大额转账", db)
        assert result is not None
        assert "重复" in result

    @pytest.mark.asyncio
    async def test_same_reason_with_whitespace(self):
        """原因内容忽略首尾空白后相同，视为重复"""
        db = make_mock_db(fetchall=[
            {"reason": " 客户频繁大额转账 ", "create_time": None},
        ])
        result = await _check_suspicious_repeat(1, "客户频繁大额转账", db)
        assert result is not None
