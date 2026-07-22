"""
硬性熔断规则引擎
5 条熔断规则（FM-01 ~ FM-05）
"""

from typing import List
from datetime import date


class CircuitBreakerResult:
    """熔断检查结果"""
    def __init__(self):
        self.passed: bool = True
        self.triggered_rules: List[dict] = []
        self.warnings: List[str] = []
        self.blocked_levels: List[str] = []


class CircuitBreaker:
    """熔断规则引擎"""

    def check_all(self, customer_data: dict) -> CircuitBreakerResult:
        """逐一检查所有熔断规则"""
        result = CircuitBreakerResult()

        self._check_fm01_age(customer_data, result)
        self._check_fm02_income_asset(customer_data, result)
        self._check_fm03_risk_expiry(customer_data, result)
        self._check_fm04_identity(customer_data, result)
        self._check_fm05_trade_abnormal(customer_data, result)

        # 有 block 级别的熔断则不通过
        for r in result.triggered_rules:
            if r.get("level") == "block":
                result.passed = False

        return result

    def _check_fm01_age(self, data: dict, result: CircuitBreakerResult):
        """FM-01: 年龄限制"""
        age = data.get("age")
        if age is None:
            return

        if age < 18:
            result.triggered_rules.append({"rule_id": "FM-01", "level": "block", "detail": "年龄<18岁，禁止开户"})
            result.warnings.append("禁止开户：年龄未满18岁")

        elif 18 <= age <= 22:
            result.triggered_rules.append({"rule_id": "FM-01", "level": "restrict", "detail": "18-22岁，R4+需监护人知情同意书"})
            result.warnings.append("购买R4及以上产品需监护人知情同意书")

        elif age > 80:
            result.triggered_rules.append({"rule_id": "FM-01", "level": "restrict", "detail": ">80岁，仅R1-R2"})
            result.warnings.append("仅允许购买R1-R2产品")
            result.blocked_levels.extend(["R3", "R4", "R5"])

        elif age > 70:
            result.triggered_rules.append({"rule_id": "FM-01", "level": "restrict", "detail": ">70岁，R3+需网点面签"})
            result.warnings.append("购买R3及以上产品需到网点当面签署风险确认书")

    def _check_fm02_income_asset(self, data: dict, result: CircuitBreakerResult):
        """FM-02: 收入与资产限制"""
        has_income = data.get("has_income", True)
        assets = data.get("total_assets", 0) or 0

        if not has_income:
            if assets < 10000:
                result.triggered_rules.append({"rule_id": "FM-02", "level": "restrict", "detail": "无收入+资产<1万，仅R1-R2"})
                result.warnings.append("无固定收入且资产不足，仅允许购买R1-R2产品")
                result.blocked_levels.extend(["R3", "R4", "R5"])
            elif assets <= 50000:
                result.warnings.append("R3产品持仓不超过总资产30%")

    def _check_fm03_risk_expiry(self, data: dict, result: CircuitBreakerResult):
        """FM-03: 风评时效检查"""
        valid_until = data.get("risk_valid_until")
        if valid_until is None:
            return

        if isinstance(valid_until, str):
            valid_until = date.fromisoformat(valid_until)

        today = date.today()
        days_since = (today - valid_until).days

        if days_since > 365:
            result.triggered_rules.append({"rule_id": "FM-03", "level": "block", "detail": "风评过期>12个月，冻结购买"})
            result.warnings.append("风险评估已过期超过12个月，已冻结购买权限，请重新评估")
            result.passed = False
        elif days_since > 180:
            result.warnings.append("风险评估即将过期，请尽快重新评估")

    def _check_fm04_identity(self, data: dict, result: CircuitBreakerResult):
        """FM-04: 身份异常检查"""
        id_expired_days = data.get("id_expired_days", 0) or 0
        identity_check_failed = data.get("identity_check_failed", False)
        on_sanction_list = data.get("on_sanction_list", False)

        if on_sanction_list:
            result.triggered_rules.append({"rule_id": "FM-04", "level": "block", "detail": "涉及制裁名单"})
            result.warnings.append("涉及制裁名单，已冻结账户")
            result.passed = False
        elif identity_check_failed:
            result.triggered_rules.append({"rule_id": "FM-04", "level": "restrict", "detail": "联网核查不通过"})
            result.warnings.append("身份核查不通过，暂停非柜面交易")
        elif id_expired_days > 90:
            result.triggered_rules.append({"rule_id": "FM-04", "level": "block", "detail": "身份证过期>90天"})
            result.warnings.append("身份证件已过期超过90天，已冻结交易权限")
            result.passed = False

    def _check_fm05_trade_abnormal(self, data: dict, result: CircuitBreakerResult):
        """FM-05: 异常交易熔断"""
        daily_loss_pct = data.get("daily_loss_pct", 0) or 0
        consecutive_redeem_pct = data.get("consecutive_redeem_pct", 0) or 0
        account_theft = data.get("account_theft_suspected", False)

        if account_theft:
            result.triggered_rules.append({"rule_id": "FM-05", "level": "block", "detail": "账户疑似盗用"})
            result.warnings.append("检测到账户可能被盗用，已立即冻结")
            result.passed = False

        if consecutive_redeem_pct > 0.4:
            result.warnings.append("连续3日大额赎回超总资产40%，需人工回访确认")

        if daily_loss_pct > 0.1:
            result.warnings.append("单日亏损超过账户10%，建议暂停交易")
