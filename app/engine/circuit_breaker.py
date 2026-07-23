"""
硬性熔断规则引擎
严格遵循《投资者风险画像研判规则》第三章（第九条 FM-01 ~ FM-05）

5 条熔断规则为强制执行硬性门槛，触发后不受综合评分影响：
  FM-01  年龄限制
  FM-02  收入与资产限制
  FM-03  风评时效检查
  FM-04  身份异常检查
  FM-05  异常交易熔断
"""

from typing import List, Optional
from datetime import date


class CircuitBreakerResult:
    """熔断检查结果"""

    def __init__(self):
        self.passed: bool = True              # 是否有 block 级别熔断
        self.triggered_rules: List[dict] = []  # 触发的规则明细
        self.warnings: List[str] = []          # 警告/提示信息
        self.blocked_levels: List[str] = []    # 被禁止的产品等级


class CircuitBreaker:
    """硬性熔断规则引擎"""

    # ── 主入口 ──────────────────────────────────────────────

    def check_all(self, customer_data: dict) -> CircuitBreakerResult:
        """逐一检查全部 5 条熔断规则"""
        result = CircuitBreakerResult()

        self._check_fm01_age(customer_data, result)
        self._check_fm02_income_asset(customer_data, result)
        self._check_fm03_risk_expiry(customer_data, result)
        self._check_fm04_identity(customer_data, result)
        self._check_fm05_trade_abnormal(customer_data, result)

        # block 级别 → 熔断不通过
        for r in result.triggered_rules:
            if r.get("level") == "block":
                result.passed = False

        return result

    # ── FM-01：年龄限制 ─────────────────────────────────────

    def _check_fm01_age(self, data: dict, result: CircuitBreakerResult):
        """
        FM-01 年龄限制（文档第九条 规则 FM-01）
        ┌──────────────┬──────────────────────────────────┐
        │ 条件          │ 处理                              │
        │ age < 18      │ 禁止开户 (block)                  │
        │ 18 ≤ age ≤ 22 │ R4+ 需监护人知情同意书 (restrict) │
        │ age > 70      │ R3+ 需网点面签确认 (restrict)     │
        │ age > 80      │ 仅 R1-R2, R3 需特殊审批 (restrict)│
        └──────────────┴──────────────────────────────────┘
        """
        age = data.get("age")
        if age is None:
            return

        if age < 18:
            result.triggered_rules.append({
                "rule_id": "FM-01", "level": "block",
                "detail": f"年龄 {age} 岁 < 18 岁，禁止开户",
            })
            result.warnings.append("禁止开户：年龄未满 18 岁")

        elif 18 <= age <= 22:
            result.triggered_rules.append({
                "rule_id": "FM-01", "level": "restrict",
                "detail": f"年龄 {age} 岁（18-22 岁），购买 R4+ 产品需监护人知情同意书",
            })
            result.warnings.append("购买 R4 及以上产品需监护人知情同意书")

        # 注意：从高到低判断，避免 80 岁被 70 岁规则先消费
        if age > 80:
            result.triggered_rules.append({
                "rule_id": "FM-01", "level": "restrict",
                "detail": f"年龄 {age} 岁 > 80 岁，仅允许 R1-R2",
            })
            result.warnings.append("仅允许购买 R1-R2 产品，R3 需特殊审批")
            result.blocked_levels.extend(["R3", "R4", "R5"])

        elif age > 70:
            result.triggered_rules.append({
                "rule_id": "FM-01", "level": "restrict",
                "detail": f"年龄 {age} 岁 > 70 岁，R3+ 需网点面签确认",
            })
            result.warnings.append("购买 R3 及以上产品需到网点当面签署风险确认书")

    # ── FM-02：收入与资产限制 ───────────────────────────────

    def _check_fm02_income_asset(self, data: dict, result: CircuitBreakerResult):
        """
        FM-02 无收入且低资产限制（文档第九条 规则 FM-02）
        ┌──────────────────────────────┬─────────────────────────┐
        │ 无收入 + 资产 < 1 万          │ 仅 R1-R2 (restrict)     │
        │ 无收入 + 资产 1-5 万          │ R1-R3，R3 ≤ 总资产 30%  │
        └──────────────────────────────┴─────────────────────────┘
        """
        has_income = data.get("has_income", True)
        if has_income:
            return  # 有收入 → 不触发

        assets = data.get("total_assets", 0) or 0

        if assets < 10000:
            result.triggered_rules.append({
                "rule_id": "FM-02", "level": "restrict",
                "detail": f"无收入且资产 {assets:.0f} 元 < 1 万元，仅允许 R1-R2",
            })
            result.warnings.append("无固定收入且资产不足 1 万元，仅允许购买 R1-R2 产品")
            result.blocked_levels.extend(["R3", "R4", "R5"])

        elif assets <= 50000:
            result.triggered_rules.append({
                "rule_id": "FM-02", "level": "restrict",
                "detail": f"无收入且资产 {assets:.0f} 元（1-5 万），R3 持仓不超过总资产 30%",
            })
            result.warnings.append("R3 产品持仓不超过总资产 30%")
            # 执行 R3 占比限制：如果 R3 持仓已超过总资产 30%，则禁止 R3 及以上
            r3_holding = data.get("r3_holding_amount", 0) or 0
            r3_limit = assets * 0.3
            if r3_holding > r3_limit:
                result.triggered_rules.append({
                    "rule_id": "FM-02", "level": "restrict",
                    "detail": f"R3 持仓 {r3_holding:.0f} 元已超过总资产 30% 限制（{r3_limit:.0f} 元），禁止 R3 及以上",
                })
                result.warnings.append(f"R3 持仓已超过总资产 30% 限制，禁止购买 R3 及以上产品")
                result.blocked_levels.extend(["R3", "R4", "R5"])

    # ── FM-03：风评时效检查 ─────────────────────────────────

    def _check_fm03_risk_expiry(self, data: dict, result: CircuitBreakerResult):
        """
        FM-03 风险评估过期（文档第九条 规则 FM-03）
        ┌──────────────────────┬──────────────────────────────────┐
        │ 风评 > 12 个月未更新   │ 冻结购买权限，仅允许赎回 (block) │
        │ 风评 > 6 个月未更新    │ 发送提醒通知 (warn)             │
        └──────────────────────┴──────────────────────────────────┘
        """
        valid_until = data.get("risk_valid_until")
        if valid_until is None:
            return

        if isinstance(valid_until, str):
            valid_until = date.fromisoformat(valid_until)

        days_since = (date.today() - valid_until).days

        if days_since > 365:
            result.triggered_rules.append({
                "rule_id": "FM-03", "level": "block",
                "detail": f"风评已过期 {days_since} 天（> 365 天），冻结购买权限",
            })
            result.warnings.append("风险评估已过期超过 12 个月，已冻结购买权限，请重新评估")
            result.passed = False

        elif days_since > 180:
            result.triggered_rules.append({
                "rule_id": "FM-03", "level": "warn",
                "detail": f"风评已过期 {days_since} 天（> 180 天），请尽快更新",
            })
            result.warnings.append("风险评估即将过期（超过 6 个月），请尽快重新评估")

    # ── FM-04：身份异常检查 ─────────────────────────────────

    def _check_fm04_identity(self, data: dict, result: CircuitBreakerResult):
        """
        FM-04 身份信息异常（文档第九条 规则 FM-04）
        ┌──────────────────────┬──────────────────────────┐
        │ 身份证过期 > 90 天    │ 冻结全部交易权限 (block)  │
        │ 联网核查不通过        │ 暂停非柜面交易 (restrict) │
        │ 涉及制裁名单          │ 立即冻结 + 上报 (block)   │
        └──────────────────────┴──────────────────────────┘
        """
        on_sanction_list      = data.get("on_sanction_list", False)
        identity_check_failed = data.get("identity_check_failed", False)
        id_expired_days       = data.get("id_expired_days", 0) or 0

        if on_sanction_list:
            result.triggered_rules.append({
                "rule_id": "FM-04", "level": "block",
                "detail": "涉及制裁名单，立即冻结账户并上报合规部门",
            })
            result.warnings.append("涉及制裁名单，已冻结账户并上报合规")
            result.passed = False
            return  # 最高优先级，不再检查其他

        if identity_check_failed:
            result.triggered_rules.append({
                "rule_id": "FM-04", "level": "restrict",
                "detail": "联网核查不通过，暂停非柜面交易",
            })
            result.warnings.append("身份核查不通过，暂停非柜面交易，要求临柜核实")

        if id_expired_days > 90:
            result.triggered_rules.append({
                "rule_id": "FM-04", "level": "block",
                "detail": f"身份证已过期 {id_expired_days} 天（> 90 天），冻结全部交易权限",
            })
            result.warnings.append("身份证件已过期超过 90 天，已冻结全部交易权限")
            result.passed = False

    # ── FM-05：异常交易熔断 ─────────────────────────────────

    def _check_fm05_trade_abnormal(self, data: dict, result: CircuitBreakerResult):
        """
        FM-05 异常交易熔断（文档第九条 规则 FM-05）
        ┌──────────────────────────────┬──────────────────────────┐
        │ 单日亏损 > 总资产 10%         │ 推送风险提示 (warn)      │
        │ 连续 3 日大额赎回 > 资产 40%  │ 触发人工回访 (restrict)  │
        │ 账户疑似盗用                  │ 立即冻结 (block)         │
        └──────────────────────────────┴──────────────────────────┘
        """
        account_theft          = data.get("account_theft_suspected", False)
        daily_loss_pct         = data.get("daily_loss_pct", 0) or 0
        consecutive_redeem_pct = data.get("consecutive_redeem_pct", 0) or 0

        if account_theft:
            result.triggered_rules.append({
                "rule_id": "FM-05", "level": "block",
                "detail": "检测到账户可能被盗用，立即冻结账户",
            })
            result.warnings.append("检测到账户可能被盗用，已立即冻结并通知客户")
            result.passed = False
            return

        if consecutive_redeem_pct > 0.4:
            result.triggered_rules.append({
                "rule_id": "FM-05", "level": "restrict",
                "detail": f"连续 3 日大额赎回累计 {consecutive_redeem_pct:.1%} > 40%，触发人工回访",
            })
            result.warnings.append("连续 3 日大额赎回超总资产 40%，需人工回访确认客户意愿")

        if daily_loss_pct > 0.1:
            result.triggered_rules.append({
                "rule_id": "FM-05", "level": "warn",
                "detail": f"单日亏损 {daily_loss_pct:.1%} > 10%，推送风险提示",
            })
            result.warnings.append("单日亏损超过账户总资产 10%，推送风险提示弹窗，建议暂停交易")


# ══════════════════════════════════════════════════════════════════
# 单元测试（与 dimension_calculator.py 联合测试）
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    print("=" * 65)
    print("  熔断规则引擎 —— 独立单元测试")
    print("=" * 65)

    breaker = CircuitBreaker()

    test_cases = [
        ("未成年人拦截", {"age": 16}, True, "block", "FM-01"),
        ("高龄 75 岁限制", {"age": 75}, False, "restrict", "FM-01"),
        ("无收入低资产", {"has_income": False, "total_assets": 5000}, False, "restrict", "FM-02"),
        ("制裁名单", {"on_sanction_list": True}, True, "block", "FM-04"),
        ("账户盗用", {"account_theft_suspected": True}, True, "block", "FM-05"),
    ]

    all_ok = True
    for label, data, expect_block, expect_level, expect_rule in test_cases:
        res = breaker.check_all(data)
        has_block = any(r["level"] == "block" for r in res.triggered_rules)
        has_match = any(
            r["rule_id"] == expect_rule and r["level"] == expect_level
            for r in res.triggered_rules
        )
        ok = (res.passed == (not expect_block)) and has_match
        status = "[PASS]" if ok else "[FAIL]"
        print(f"  {status} {label}: passed={res.passed} (expected={not expect_block})")
        if not ok:
            all_ok = False

    print(f"\n  {'=== ALL PASSED ===' if all_ok else '=== SOME FAILED ==='}\n")
