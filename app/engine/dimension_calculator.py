"""
四维度打分计算器 + 统一研判入口
严格遵循《投资者风险画像研判规则》(JR-RULE-2024-001 V2.3)

公式对齐：
  维度一 = (年龄 + 学历 + 职业 + 收入 + 资产) ÷ 5 ÷ 10 × 25   (满分25)
  维度二 = (投资年限 + 产品复杂度 + 交易频率 + 历史收益) ÷ 4 ÷ 10 × 25 (满分25)
  维度三 = 风评映射分 + 情绪化扣分 + 亏损承受调整   [0, 30] 区间
  维度四 = 异常行为计分   (满分20)
  综合得分 = Σ(各维度得分)   (满分100)
"""

from typing import Dict, Optional, List, Tuple
from app.config.rules_config import (
    # 维度一
    AGE_SCORE, EDUCATION_SCORE, OCCUPATION_SCORE, INCOME_SCORE, ASSET_SCORE,
    # 维度二
    INVESTMENT_YEARS_SCORE, PRODUCT_COMPLEXITY_SCORE,
    TRADE_FREQUENCY_SCORE, HISTORICAL_RETURN_SCORE,
    # 维度三
    RISK_ASSESSMENT_MAPPING, EMOTIONAL_TRADING_PENALTY, LOSS_TOLERANCE_ADJUSTMENT,
    # 维度四
    BEHAVIOR_ABNORMAL_SCORE, BEHAVIOR_ABNORMAL_RULES,
)


# ══════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════

def _score_or_default(mapping: dict, key, default: int = 3) -> int:
    """从映射表取分，未匹配返回默认保守分"""
    return mapping.get(key, default)


# ══════════════════════════════════════════════════════════════════
# 维度一：基础属性特征（满分 25 分）
# 公式: (年龄 + 学历 + 职业 + 收入 + 资产) ÷ 5 ÷ 10 × 25
# ══════════════════════════════════════════════════════════════════

class BasicDimension:
    """
    维度一：基础属性特征
    数据来源：开户信息 / KYC 资料
    """

    @staticmethod
    def _age_to_score(age: Optional[int]) -> int:
        """年龄 → 分值映射（含边界处理）"""
        if age is None:
            return 3  # 保守默认
        if age < 18:
            return 0  # 未成年人（熔断层会拦截）
        elif age <= 25:
            return AGE_SCORE["18-25"]
        elif age <= 35:
            return AGE_SCORE["26-35"]
        elif age <= 45:
            return AGE_SCORE["36-45"]
        elif age <= 55:
            return AGE_SCORE["46-55"]
        elif age <= 65:
            return AGE_SCORE["56-65"]
        else:
            return AGE_SCORE["65+"]

    def calc(self, customer: dict) -> dict:
        """
        计算维度一得分
        公式: (年龄 + 学历 + 职业 + 收入 + 资产) ÷ 5 ÷ 10 × 25
        """
        age_score   = self._age_to_score(customer.get("age"))
        edu_score   = _score_or_default(EDUCATION_SCORE, customer.get("education"), 4)
        occ_score   = _score_or_default(OCCUPATION_SCORE, customer.get("occupation"), 5)
        inc_score   = _score_or_default(INCOME_SCORE, customer.get("annual_income_range"), 3)
        ast_score   = _score_or_default(ASSET_SCORE, customer.get("asset_range"), 4)

        # 严格公式: 均值 ÷ 10 × 25
        mean_raw = (age_score + edu_score + occ_score + inc_score + ast_score) / 5.0
        dimension_score = round(mean_raw / 10.0 * 25.0, 2)

        return {
            "score": min(dimension_score, 25.0),
            "detail": {
                "age": age_score,
                "education": edu_score,
                "occupation": occ_score,
                "income": inc_score,
                "assets": ast_score,
            },
        }


# ══════════════════════════════════════════════════════════════════
# 维度二：投资经验特征（满分 25 分）
# 公式: (投资年限 + 产品复杂度 + 交易频率 + 历史收益) ÷ 4 ÷ 10 × 25
# ══════════════════════════════════════════════════════════════════

class ExperienceDimension:
    """
    维度二：投资经验特征
    数据来源：交易流水 / 持仓数据
    """

    def calc(self, customer: dict) -> dict:
        """
        计算维度二得分
        公式: (投资年限 + 产品复杂度 + 交易频率 + 历史收益) ÷ 4 ÷ 10 × 25
        """
        years_score      = _score_or_default(INVESTMENT_YEARS_SCORE, customer.get("investment_years"), 2)
        complexity_score = _score_or_default(PRODUCT_COMPLEXITY_SCORE, customer.get("max_product_type"), 2)
        freq_score       = _score_or_default(TRADE_FREQUENCY_SCORE, customer.get("trade_frequency"), 5)
        return_score     = _score_or_default(HISTORICAL_RETURN_SCORE, customer.get("historical_return"), 3)

        # 严格公式: 均值 ÷ 10 × 25
        mean_raw = (years_score + complexity_score + freq_score + return_score) / 4.0
        dimension_score = round(mean_raw / 10.0 * 25.0, 2)

        return {
            "score": min(dimension_score, 25.0),
            "detail": {
                "years": years_score,
                "complexity": complexity_score,
                "frequency": freq_score,
                "returns": return_score,
            },
        }


# ══════════════════════════════════════════════════════════════════
# 维度三：风险偏好特征（满分 30 分，下限 0 分）
# 公式: 风评映射分 + 情绪化交易扣分 + 亏损承受调整
# ══════════════════════════════════════════════════════════════════

class RiskPrefDimension:
    """
    维度三：风险偏好特征
    数据来源：风评问卷 / 行为分析
    """

    def calc(self, customer: dict) -> dict:
        # ── 7.1 风评得分映射 ──
        risk_level = customer.get("risk_assessment_level") or "C1"
        assessment_score = RISK_ASSESSMENT_MAPPING.get(risk_level, 5)

        # ── 7.2 情绪化交易扣分 ──
        emotional_penalty = 0
        triggered_emotions = []
        for rule in EMOTIONAL_TRADING_PENALTY:
            flag_key = f"emotional_{rule['behavior']}"
            if customer.get(flag_key, False):
                emotional_penalty += rule["penalty"]
                triggered_emotions.append(rule["behavior"])

        # ── 7.3 亏损承受能力调整 ──
        loss_tolerance = customer.get("loss_tolerance", "10%-20%")
        loss_adj = LOSS_TOLERANCE_ADJUSTMENT.get(loss_tolerance, 0)

        # 严格公式: 上限 30，下限 0
        dimension_score = max(0.0, min(30.0, assessment_score + emotional_penalty + loss_adj))

        return {
            "score": dimension_score,
            "detail": {
                "assessment": assessment_score,
                "emotional_deduction": emotional_penalty,
                "emotional_triggers": triggered_emotions,
                "loss_tolerance": loss_adj,
            },
        }


# ══════════════════════════════════════════════════════════════════
# 维度四：行为异常特征（满分 20 分）
# 8 种异常行为 → 汇总计分
# ══════════════════════════════════════════════════════════════════

class BehaviorDimension:
    """
    维度四：行为异常特征
    数据来源：实时交易流水
    """

    def calc(self, customer: dict) -> dict:
        abnormal_behaviors: List[dict] = customer.get("abnormal_behaviors", [])

        if not abnormal_behaviors:
            score = BEHAVIOR_ABNORMAL_SCORE["无异常"]
            risk_desc = "无异常"
        else:
            low_count  = sum(1 for b in abnormal_behaviors if b.get("risk") == "低")
            mid_count  = sum(1 for b in abnormal_behaviors if b.get("risk") == "中")
            high_count = sum(1 for b in abnormal_behaviors if b.get("risk") == "高")

            if high_count > 0:
                score = BEHAVIOR_ABNORMAL_SCORE["任何高风险"]
                risk_desc = "任何高风险"
            elif mid_count >= 3:
                score = BEHAVIOR_ABNORMAL_SCORE["3项以上中风险"]
                risk_desc = "3项以上中风险"
            elif mid_count >= 1:
                score = BEHAVIOR_ABNORMAL_SCORE["1-2项中风险"]
                risk_desc = "1-2项中风险"
            elif low_count >= 1:
                score = BEHAVIOR_ABNORMAL_SCORE["1-2项低风险"]
                risk_desc = "1-2项低风险"
            else:
                score = BEHAVIOR_ABNORMAL_SCORE["无异常"]
                risk_desc = "无异常"

        return {
            "score": score,
            "detail": {
                "abnormal_count": len(abnormal_behaviors),
                "risk_level": risk_desc,
                "behaviors": [b.get("id", b.get("name", "")) for b in abnormal_behaviors],
            },
        }


# ══════════════════════════════════════════════════════════════════
# 统一计算器
# ══════════════════════════════════════════════════════════════════

class DimensionCalculator:
    """四维度统一计算器"""

    def __init__(self):
        self.basic      = BasicDimension()
        self.experience = ExperienceDimension()
        self.risk_pref  = RiskPrefDimension()
        self.behavior   = BehaviorDimension()

    def calc_all(self, customer_data: dict) -> dict:
        """计算全部四个维度，返回带明细的得分字典"""
        return {
            "basic":      self.basic.calc(customer_data),
            "experience": self.experience.calc(customer_data),
            "risk_pref":  self.risk_pref.calc(customer_data),
            "behavior":   self.behavior.calc(customer_data),
        }

    def calc_total(self, customer_data: dict) -> float:
        """
        计算综合得分（满分 100）
        综合得分 = 维度一 + 维度二 + 维度三 + 维度四
        （各维度得分已内含权重，直接求和即是 100 分制）
        """
        scores = self.calc_all(customer_data)
        total = sum(scores[dim]["score"] for dim in ["basic", "experience", "risk_pref", "behavior"])
        return round(total, 2)


# ══════════════════════════════════════════════════════════════════
# 等级映射（复用 score_mapper 中的实现，避免重复定义）
# ══════════════════════════════════════════════════════════════════

from app.engine.score_mapper import map_score_to_risk_level, get_suitable_products


# ══════════════════════════════════════════════════════════════════
# 统一研判入口 —— evaluate_customer
# ══════════════════════════════════════════════════════════════════

def evaluate_customer(customer_data: dict) -> dict:
    """
    客户风险画像统一研判入口。

    输入 customer_data 字典（字段见下方示例），返回完整研判结果字典：

    Returns:
        {
            "passed": bool,              # 是否通过熔断检查
            "total_score": float,        # 综合得分 (0-100)
            "risk_level": str,           # 风险等级代码 C1-C5
            "risk_name": str,            # 风险等级名称
            "dimensions": {              # 四维度得分明细
                "basic":      {"score": ..., "detail": {...}},
                "experience": {"score": ..., "detail": {...}},
                "risk_pref":  {"score": ..., "detail": {...}},
                "behavior":   {"score": ..., "detail": {...}},
            },
            "circuit_breakers": [        # 触发的熔断规则列表
                {"rule_id": "FM-01", "level": "restrict", "detail": "..."}
            ],
            "warnings": [str, ...],      # 警告信息
            "suitable_products": [str, ...],  # 可购产品等级
        }
    """
    from app.engine.circuit_breaker import CircuitBreaker

    calculator = DimensionCalculator()
    breaker = CircuitBreaker()

    # ── Step 1: 四维度打分 ──
    dimensions = calculator.calc_all(customer_data)

    # ── Step 2: 综合评分并映射等级 ──
    total_score = sum(d["score"] for d in dimensions.values())
    total_score = round(total_score, 2)
    risk_level, risk_name = map_score_to_risk_level(total_score)

    # ── Step 3: 熔断检查 ──
    cb_result = breaker.check_all(customer_data)

    # ── Step 4: 熔断可能限制产品范围 ──
    suitable = get_suitable_products(risk_level)
    if cb_result.blocked_levels:
        suitable = [p for p in suitable if p not in cb_result.blocked_levels]

    # ── Step 5: 组装结果 ──
    return {
        "passed": cb_result.passed,
        "total_score": total_score,
        "risk_level": risk_level,
        "risk_name": risk_name,
        "dimensions": dimensions,
        "circuit_breakers": cb_result.triggered_rules,
        "warnings": cb_result.warnings,
        "suitable_products": suitable,
    }


# ══════════════════════════════════════════════════════════════════
# 单元测试
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    print("=" * 65)
    print("  投资者风险画像研判规则引擎 —— 单元测试")
    print("  规则版本: JR-RULE-2024-001 V2.3")
    print("=" * 65)

    # ─── 测试客户数据 ──────────────────────────────────────────
    test_customers = [
        {
            "name": "张三（稳健上班族）",
            "data": {
                "age": 30,
                "education": "本科",
                "occupation": "大型国企/上市公司正式员工",
                "annual_income_range": "10-30万",
                "asset_range": "20-50万",
                "total_assets": 300000,
                "has_income": True,
                "investment_years": "3-5年",
                "max_product_type": "混合基金/指数基金(R3)",
                "trade_frequency": "低频",
                "historical_return": "5%~15%",
                "risk_assessment_level": "C3",
                "loss_tolerance": "10%-20%",
                "abnormal_behaviors": [],
            },
        },
        {
            "name": "李四（激进年轻人）",
            "data": {
                "age": 24,
                "education": "硕士及以上",
                "occupation": "专业技术人员",
                "annual_income_range": "30-50万",
                "asset_range": "100-500万",
                "total_assets": 2000000,
                "has_income": True,
                "investment_years": "1-3年",
                "max_product_type": "股票/股票基金/ETF(R4)",
                "trade_frequency": "高频",
                "historical_return": ">15%",
                "risk_assessment_level": "C4",
                "loss_tolerance": "20%-40%",
                "emotional_追涨杀跌": True,
                "emotional_FOMO加仓": True,
                "abnormal_behaviors": [
                    {"id": "B001", "name": "频繁赎回", "risk": "中"},
                ],
            },
        },
        {
            "name": "王奶奶（高龄保守）— 熔断测试",
            "data": {
                "age": 72,
                "education": "高中及以下",
                "occupation": "退休",
                "annual_income_range": "<10万",
                "asset_range": "50-100万",
                "total_assets": 600000,
                "has_income": True,
                "investment_years": ">10年",
                "max_product_type": "纯债基金/银行理财(R1-R2)",
                "trade_frequency": "极低频",
                "historical_return": "-5%~5%",
                "risk_assessment_level": "C1",
                "loss_tolerance": "不能承受任何亏损",
                "abnormal_behaviors": [],
            },
        },
        {
            "name": "赵六（跌破底线）— 熔断测试",
            "data": {
                "age": 17,
                "education": "高中及以下",
                "occupation": "在校学生",
                "annual_income_range": None,
                "asset_range": "<5万",
                "total_assets": 3000,
                "has_income": False,
                "investment_years": "无投资经验",
                "max_product_type": "仅银行存款",
                "trade_frequency": "极低频",
                "historical_return": "无历史记录",
                "risk_assessment_level": None,
                "loss_tolerance": None,
                "abnormal_behaviors": [],
                "is_student": True,
            },
        },
    ]

    calculator = DimensionCalculator()
    from app.engine.circuit_breaker import CircuitBreaker
    breaker = CircuitBreaker()

    all_passed = True
    for tc in test_customers:
        print(f"\n{'─' * 65}")
        print(f"  [CASE] {tc['name']}")
        print(f"{'─' * 65}")

        result = evaluate_customer(tc["data"])

        # ── 四维度明细 ──
        print(f"\n  【四维度打分】")
        dim_names = {
            "basic": "维度一·基础属性", "experience": "维度二·投资经验",
            "risk_pref": "维度三·风险偏好", "behavior": "维度四·行为异常",
        }
        for dim_key, dim_label in dim_names.items():
            d = result["dimensions"][dim_key]
            print(f"    {dim_label:20s} → {d['score']:6.2f} 分   明细: {d['detail']}")

        # ── 综合结果 ──
        print(f"\n  【综合结果】")
        print(f"    综合得分:  {result['total_score']:.2f} / 100")
        print(f"    风险等级:  {result['risk_level']} （{result['risk_name']}）")
        print(f"    可购产品:  {', '.join(result['suitable_products'])}")
        print(f"    熔断通过:  {'[YES]' if result['passed'] else '[NO]'}")

        # ── 熔断规则 ──
        if result["circuit_breakers"]:
            print(f"\n  【触发熔断】")
            for cb in result["circuit_breakers"]:
                print(f"    [{cb.get('level','')}] {cb.get('rule_id','')}: {cb.get('detail','')}")

        if result["warnings"]:
            print(f"\n  【警告】")
            for w in result["warnings"]:
                print(f"    [WARN] {w}")

        # ── 人工验证关键断言 ──
        data = tc["data"]
        # 张三: 年龄30→10, 本科→8, 国企→9, 10-30万→5, 20-50万→6
        # 均值=(10+8+9+5+6)/5=7.6, 维度一=7.6/10*25=19.0
        if data["age"] == 30:
            expected_basic = round((10 + 8 + 9 + 5 + 6) / 5 / 10 * 25, 2)
            actual_basic = result["dimensions"]["basic"]["score"]
            if abs(expected_basic - actual_basic) < 0.01:
                print(f"\n    [PASS] 维度一公式验证通过: {expected_basic} == {actual_basic}")
            else:
                print(f"\n    [FAIL] 维度一公式验证失败: 期望 {expected_basic}, 实际 {actual_basic}")
                all_passed = False

        # 赵六: 年龄=17 应触发 FM-01 熔断
        if data["age"] == 17:
            fm01_triggered = any(cb["rule_id"] == "FM-01" and cb["level"] == "block"
                                 for cb in result["circuit_breakers"])
            if fm01_triggered and not result["passed"]:
                print(f"    [PASS] 未成年人熔断验证通过 (FM-01)")
            else:
                print(f"    [FAIL] 未成年人熔断验证失败")
                all_passed = False

        # 王奶奶: 年龄=72 应触发 FM-01 restrict
        if data["age"] == 72:
            fm01_restrict = any(cb["rule_id"] == "FM-01" and cb["level"] == "restrict"
                                for cb in result["circuit_breakers"])
            if fm01_restrict:
                print(f"    [PASS] 高龄限制熔断验证通过 (FM-01)")
            else:
                print(f"    [FAIL] 高龄限制熔断验证失败")
                all_passed = False

    print(f"\n{'=' * 65}")
    if all_passed:
        print("  === ALL TESTS PASSED ===")
    else:
        print("  === SOME TESTS FAILED ===")
    print(f"{'=' * 65}\n")
