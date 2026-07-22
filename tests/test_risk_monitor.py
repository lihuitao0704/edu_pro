"""风控监测单元测试"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tool.risk_monitor_rules import ALL_AML_RULES
from app.service.risk_monitor_service import RiskMonitorService


def test_count():
    assert len(ALL_AML_RULES) == 20, f"规则数应为20, 实际{len(ALL_AML_RULES)}"
    print("[OK] 规则总数=20")


def test_normal():
    """正常交易不触发"""
    tx = {"customer_id": 1, "amount": 10000, "transaction_type": "purchase"}
    svc = RiskMonitorService()
    assert len(svc.evaluate_all(tx)) == 0
    print("[OK] 正常交易不触发")


def test_large_cash():
    """R001: 大额现金"""
    tx = {"customer_id": 5, "amount": 120000, "transaction_type": "cash",
          "timestamp": "2026-07-22T10:00:00", "has_night_history_90d": True}
    svc = RiskMonitorService()
    triggered = svc.evaluate_all(tx)
    assert any(r.rule_id == "R001" for r in triggered)
    print("[OK] R001 大额现金交易")


def test_elderly():
    """R016: 老年客户保护"""
    tx = {"customer_id": 3, "amount": 120000, "age": 65,
          "monthly_avg_12m": 10000, "transaction_type": "transfer",
          "has_night_history_90d": True, "timestamp": "2026-07-22T10:00:00"}
    svc = RiskMonitorService()
    triggered = svc.evaluate_all(tx)
    assert any(r.rule_id == "R016" for r in triggered)
    print("[OK] R016 老年客户异常大额")


def test_grading():
    """预警分级"""
    svc = RiskMonitorService()
    from app.tool.risk_monitor_rules import LargeTransactionRule, QuickInOutRule

    assert svc.grade([], [], {}) is None
    assert svc.grade([LargeTransactionRule()], [], {}) == "low"
    assert svc.grade([LargeTransactionRule(), QuickInOutRule()], [], {}) == "medium"

    from app.tool.risk_monitor_rules import AmountMismatchRule, FrequentSmallRule
    rules = [LargeTransactionRule(), QuickInOutRule(), AmountMismatchRule(), FrequentSmallRule()]
    assert svc.grade(rules, [], {}) == "high"
    print("[OK] 预警分级: low/medium/high")


if __name__ == "__main__":
    print("=== 风控监测测试 ===\n")
    test_count()
    test_normal()
    test_large_cash()
    test_elderly()
    test_grading()
    print("\nAll tests passed!")
