"""
核心引擎单元测试
测试四维度打分、熔断规则、等级映射、置信度、特殊场景
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0


def check(name: str, actual, expected):
    global PASS, FAIL
    if actual == expected:
        PASS += 1
        print(f"  [OK] {name}: {actual}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}: 期望 {expected}, 实际 {actual}")


def check_range(name: str, actual, low, high):
    global PASS, FAIL
    if low <= actual <= high:
        PASS += 1
        print(f"  [OK] {name}: {actual} (范围 [{low}, {high}])")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}: {actual} 不在范围 [{low}, {high}]")


def check_contains(name: str, actual, expected_substring):
    global PASS, FAIL
    if expected_substring in str(actual):
        PASS += 1
        print(f"  [OK] {name}: 包含 '{expected_substring}'")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}: '{actual}' 不包含 '{expected_substring}'")


# ========== 测试1: 四维度打分 ==========
print("\n" + "=" * 60)
print("1. 四维度打分计算器")
print("=" * 60)

from app.engine.dimension_calculator import DimensionCalculator

calc = DimensionCalculator()

# 模拟客户A数据（25岁、本科、互联网、年收入15万、资产12万）
customer_a = {
    "age": 25,
    "education": "本科",
    "occupation": "专业技术人员",
    "annual_income_range": "10-30万",
    "asset_range": "5-20万",
    "total_assets": 120000,
    "has_income": True,
    "investment_years": "1-3年",
    "max_product_type": "混合基金/指数基金(R3)",
    "trade_frequency": "低频",
    "historical_return": "5%~15%",
    "risk_assessment_level": "C2",
    "loss_tolerance": "10%-20%",
    "abnormal_behaviors": [],
}

scores = calc.calc_all(customer_a)

print("\n  [维度一] 基础属性特征（满分25）:")
check_range("  得分", scores["basic"]["score"], 10, 25)
check("  年龄分", scores["basic"]["detail"]["age"], 8)  # 25岁属于18-25区间→8分
check("  学历分", scores["basic"]["detail"]["education"], 8)
check("  职业分", scores["basic"]["detail"]["occupation"], 8)

print("\n  [维度二] 投资经验特征（满分25）:")
check_range("  得分", scores["experience"]["score"], 10, 25)
check("  投资年限分", scores["experience"]["detail"]["years"], 6)
check("  产品复杂度分", scores["experience"]["detail"]["complexity"], 7)

print("\n  [维度三] 风险偏好特征（满分30）:")
check_range("  得分", scores["risk_pref"]["score"], 5, 25)
check("  风评映射分", scores["risk_pref"]["detail"]["assessment"], 10)

print("\n  [维度四] 行为异常特征（满分20）:")
check("  得分", scores["behavior"]["score"], 20)
check("  异常数", scores["behavior"]["detail"]["abnormal_count"], 0)

# ========== 测试2: 有异常行为的客户 ==========
print("\n\n" + "=" * 60)
print("2. 有异常行为的客户打分")
print("=" * 60)

customer_b = dict(customer_a)
customer_b["abnormal_behaviors"] = [
    {"id": "B001", "name": "频繁赎回", "risk": "中"},
    {"id": "B002", "name": "大额集中交易", "risk": "中"},
]
scores_b = calc.calc_all(customer_b)
print("\n  [维度四] 2项中风险异常:")
check("  得分", scores_b["behavior"]["score"], 10)
check("  异常数", scores_b["behavior"]["detail"]["abnormal_count"], 2)


customer_c = dict(customer_a)
customer_c["abnormal_behaviors"] = [
    {"id": "B005", "name": "分散转出", "risk": "高"},
]
scores_c = calc.calc_all(customer_c)
print("\n  [维度四] 1项高风险异常:")
check("  得分", scores_c["behavior"]["score"], 0)

# ========== 测试3: 分数映射 ==========
print("\n\n" + "=" * 60)
print("3. 综合评分与等级映射")
print("=" * 60)

from app.engine.score_mapper import (
    map_score_to_risk_level, calc_total_score,
    get_suitable_products, check_suitability,
)

scores_for_total = {k: v["score"] for k, v in scores.items()}
total = calc_total_score(scores_for_total)
level, name = map_score_to_risk_level(total)
print(f"\n  客户A综合分: {total}, 等级: {level}({name})")
check_range("  客户A综合分", total, 55, 80)  # 16.5+17.5+10+20 = 64

print("\n  等级映射表:")
for ts in [10, 30, 50, 70, 90]:
    l, n = map_score_to_risk_level(ts)
    print(f"    {ts}分 → {l}({n})")

check("  10分→保守型", map_score_to_risk_level(10)[1], "保守型")
check("  30分→稳健型", map_score_to_risk_level(30)[1], "稳健型")
check("  50分→平衡型", map_score_to_risk_level(50)[1], "平衡型")
check("  70分→进取型", map_score_to_risk_level(70)[1], "进取型")
check("  90分→激进型", map_score_to_risk_level(90)[1], "激进型")

print("\n  适当性匹配:")
check("  C1→R1-R2", get_suitable_products("C1"), ["R1", "R2"])
check("  C2→R1-R3", get_suitable_products("C2"), ["R1", "R2", "R3"])
check("  C5→R1-R5", get_suitable_products("C5"), ["R1", "R2", "R3", "R4", "R5"])
check("  适当性C1不可买R4", check_suitability("C1", "R4"), False)
check("  适当性C3可买R3", check_suitability("C3", "R3"), True)

# ========== 测试4: 熔断规则 ==========
print("\n\n" + "=" * 60)
print("4. 硬性熔断规则")
print("=" * 60)

from app.engine.circuit_breaker import CircuitBreaker

breaker = CircuitBreaker()

# 测试年龄<18
print("\n  [FM-01] 年龄15岁未成年人:")
result = breaker.check_all({"age": 15})
check("  触发拦阻", result.passed, False)
check_contains("  原因", str(result.warnings), "禁止开户")

# 测试年龄18-22
print("\n  [FM-01] 年龄20岁大学生:")
result = breaker.check_all({"age": 20})
check("  通过", result.passed, True)
check_contains("  警告", str(result.warnings), "监护人")

# 测试年龄>80
print("\n  [FM-01] 年龄85岁老人:")
result = breaker.check_all({"age": 85})
check("  通过但有限制", result.passed, True)
check("  限制R3-R5", "R3" in result.blocked_levels, True)
check("  限制R3-R5", "R4" in result.blocked_levels, True)

# 测试风评过期
from datetime import date, timedelta
print("\n  [FM-03] 风评过期400天:")
expired = date.today() - timedelta(days=400)
result = breaker.check_all({"risk_valid_until": expired.isoformat()})
check("  触发冻结", result.passed, False)
check_contains("  原因", str(result.warnings), "过期")

# 测试风评未过期
print("\n  [FM-03] 风评刚完成:")
valid = date.today() + timedelta(days=300)
result = breaker.check_all({"risk_valid_until": valid.isoformat()})
check("  正常通过", result.passed, True)
check("  无警告", len(result.warnings), 0)

# 测试制裁名单
print("\n  [FM-04] 涉及制裁名单:")
result = breaker.check_all({"on_sanction_list": True})
check("  冻结", result.passed, False)

# 测试账户被盗
print("\n  [FM-05] 账户疑似盗用:")
result = breaker.check_all({"account_theft_suspected": True})
check("  冻结", result.passed, False)

# ========== 测试5: 置信度 ==========
print("\n\n" + "=" * 60)
print("5. 置信度计算")
print("=" * 60)

from app.engine.confidence import ConfidenceCalculator

conf = ConfidenceCalculator()

print("\n  来源初始值:")
check("  风评问卷", conf.calc_single("questionnaire"), 0.9)
check("  AI提取", conf.calc_single("ai_extract"), 0.6)
check("  用户自述", conf.calc_single("self_report"), 0.4)
check("  默认", conf.calc_single("default"), 0.2)

print("\n  多证据累积:")
score = conf.calc_single("ai_extract", evidence_count=3)
check_range("  3次证据", score, 0.6, 0.75)

print("\n  冲突惩罚:")
score = conf.calc_single("questionnaire", evidence_count=1, conflict_count=3)
check_range("  1证据+3冲突", score, 0.6, 0.9)

print("\n  来源优先级:")
check("  问卷 > AI", conf.compare_source_priority("questionnaire", "ai_extract"), 1)
check("  AI > 默认", conf.compare_source_priority("ai_extract", "default"), 1)
check("  默认最低", conf.compare_source_priority("default", "questionnaire"), -1)

print("\n  标签冲突解决:")
result = conf.resolve_conflict(
    {"tag_value": "稳健型", "source": "questionnaire"},
    {"tag_value": "进取型", "source": "ai_extract"},
)
check("  问卷覆盖AI", result[0]["source"], "questionnaire")

# ========== 测试6: 特殊场景 ==========
print("\n\n" + "=" * 60)
print("6. 特殊场景处理")
print("=" * 60)

from app.engine.special_case import SpecialCaseHandler

handler = SpecialCaseHandler()

# 信息不完整
print("\n  收入缺失:")
result = handler.handle({"annual_income_range": None}, "C3")
check("  下调评级", result.downgrade_levels, 1)
check_contains("  原因", str(result.adjustments), "最低工资")

# 自评冲突
print("\n  自评C5 vs AI评估C2 (差3档):")
result = handler.handle({"self_assessment_level": "C5"}, "C2")
check("  需要人工复核", result.requires_manual_review, True)

print("\n  自评C3 vs AI评估C2 (差1档):")
result = handler.handle({"self_assessment_level": "C3"}, "C2")
check_contains("  允许申请复核", str(result.adjustments), "人工复核")

# 在校学生
print("\n  在校学生:")
result = handler.handle({"is_student": True}, "C3")
check("  下调评级", result.downgrade_levels, 2)  # 收入缺失+学生身份
check("  限制R2以内", result.product_restrictions, ["R1", "R2"])

# ========== 测试7: 配置加载 ==========
print("\n\n" + "=" * 60)
print("7. 配置与模型加载")
print("=" * 60)

from app.config.rules_config import (
    DIMENSION_WEIGHTS, RISK_LEVEL_MAPPING, CIRCUIT_BREAKER_RULES,
    ASSET_ALLOCATION_TEMPLATES, SUITABILITY_MATRIX,
)
from app.config.settings import get_settings

settings = get_settings()

print("\n  维度权重:")
check("  总和=1.0", round(sum(DIMENSION_WEIGHTS.values()), 2), 1.0)

print("\n  等级映射数量:")
check("  5个等级", len(RISK_LEVEL_MAPPING), 5)

print("\n  熔断规则:")
check("  5条规则", len(CIRCUIT_BREAKER_RULES), 5)

print("\n  资产配置模板:")
check("  5种等级配置", len(ASSET_ALLOCATION_TEMPLATES), 5)
check("  C1配置总和", round(sum(ASSET_ALLOCATION_TEMPLATES["C1"].values()), 2), 1.0)

print("\n  配置项加载:")
print(f"配置: mysql={settings.mysql.host}, llm={settings.llm.openai_model_chat}")
check("  MySQL可连接", bool(settings.mysql.host), True)
check("  LLM已配置", bool(settings.llm.openai_model_chat), True)
check("  推荐TopN", settings.recommendation.top_n, 3)
check_range("  画像置信度衰减率", settings.profile.confidence_decay_rate, 0.1, 0.5)

# ========== 结果汇总 ==========
print("\n\n" + "=" * 60)
print("测试结果汇总")
print("=" * 60)
total_tests = PASS + FAIL
print(f"\n  通过: {PASS} / {total_tests}")
print(f"  失败: {FAIL} / {total_tests}")
print(f"  通过率: {PASS / total_tests * 100:.1f}%")

if FAIL > 0:
    print(f"\n  [WARN] 有 {FAIL} 个测试未通过，请检查！")
    sys.exit(1)
else:
    print(f"\n  [PASS] 全部通过！")
    sys.exit(0)
