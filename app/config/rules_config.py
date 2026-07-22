"""
研判规则配置
基于《投资者风险画像研判规则》(JR-RULE-2024-001 V2.3)
所有评分表、权重、阈值集中管理，便于规则调优
"""

from typing import Dict, List, Tuple
from dataclasses import dataclass, field


# ==================== 维度权重 ====================

DIMENSION_WEIGHTS = {
    "basic": 0.25,      # 维度一：基础属性特征
    "experience": 0.25,  # 维度二：投资经验特征
    "risk_pref": 0.30,   # 维度三：风险偏好特征
    "behavior": 0.20,    # 维度四：行为异常特征
}

# ==================== 维度一：基础属性特征 ====================

# 5.1 年龄评分 (0-10)
AGE_SCORE: Dict[str, int] = {
    "18-25": 8,
    "26-35": 10,
    "36-45": 9,
    "46-55": 7,
    "56-65": 5,
    "65+": 3,
}

# 5.2 学历评分 (0-10)
EDUCATION_SCORE: Dict[str, int] = {
    "高中及以下": 4,
    "大专": 6,
    "本科": 8,
    "硕士及以上": 10,
}

# 5.3 职业评分 (0-10)
OCCUPATION_SCORE: Dict[str, int] = {
    "公务员/事业单位": 10,
    "大型国企/上市公司正式员工": 9,
    "专业技术人员": 8,
    "中小企业员工": 6,
    "自由职业者": 5,
    "个体工商户": 5,
    "无固定职业": 2,
    "退休": 4,
}

# 5.4 年收入评分 (0-10)
INCOME_SCORE: Dict[str, int] = {
    "<10万": 3,
    "10-30万": 5,
    "30-50万": 7,
    "50-100万": 8,
    "100-300万": 9,
    ">300万": 10,
}

# 5.5 资产规模评分 (0-10)
ASSET_SCORE: Dict[str, int] = {
    "<5万": 2,
    "5-20万": 4,
    "20-50万": 6,
    "50-100万": 7,
    "100-500万": 8,
    "500-1000万": 9,
    ">1000万": 10,
}

# ==================== 维度二：投资经验特征 ====================

# 6.1 投资年限评分 (0-10)
INVESTMENT_YEARS_SCORE: Dict[str, int] = {
    "无投资经验": 2,
    "<1年": 4,
    "1-3年": 6,
    "3-5年": 8,
    "5-10年": 9,
    ">10年": 10,
}

# 6.2 产品复杂度评分 (0-10)
PRODUCT_COMPLEXITY_SCORE: Dict[str, int] = {
    "仅银行存款": 2,
    "货币基金/国债": 4,
    "纯债基金/银行理财(R1-R2)": 5,
    "混合基金/指数基金(R3)": 7,
    "股票/股票基金/ETF(R4)": 8,
    "期货/期权/私募/结构化产品(R5)": 10,
}

# 6.3 交易频率评分 (0-10)
TRADE_FREQUENCY_SCORE: Dict[str, int] = {
    "极低频": 5,
    "低频": 7,
    "中频": 8,
    "高频": 6,  # 过度交易，扣分项
}

# 6.4 历史收益评分 (0-10)
HISTORICAL_RETURN_SCORE: Dict[str, int] = {
    "无历史记录": 3,
    "<-15%": 3,
    "-15%~-5%": 4,
    "-5%~5%": 6,
    "5%~15%": 8,
    ">15%": 9,
}

# ==================== 维度三：风险偏好特征 ====================

# 7.1 风评得分映射
RISK_ASSESSMENT_MAPPING: Dict[str, int] = {
    "C1": 5,
    "C2": 10,
    "C3": 15,
    "C4": 20,
    "C5": 25,
}

# 7.2 情绪化交易扣分
EMOTIONAL_TRADING_PENALTY = [
    {"behavior": "追涨杀跌", "description": "净值新高后3日内买入/新低后3日内卖出", "penalty": -3},
    {"behavior": "恐慌赎回", "description": "市场大跌(>5%)当日赎回超持仓50%", "penalty": -5},
    {"behavior": "FOMO加仓", "description": "连续3日上涨后大额加仓超月均3倍", "penalty": -2},
    {"behavior": "频繁改策略", "description": "90天内调整投资组合配置超过3次", "penalty": -3},
]

# 7.3 亏损承受能力调整
LOSS_TOLERANCE_ADJUSTMENT: Dict[str, int] = {
    "不能承受任何亏损": -5,
    "5%以内": -2,
    "10%-20%": 0,
    "20%-40%": 3,
    "40%以上": 5,
}

# ==================== 维度四：行为异常特征 ====================

BEHAVIOR_ABNORMAL_RULES = [
    {"id": "B001", "name": "频繁赎回", "rule": "30天内赎回次数≥5次", "risk": "中"},
    {"id": "B002", "name": "大额集中交易", "rule": "单日交易金额超过账户总资产50%", "risk": "中"},
    {"id": "B003", "name": "非正常时段交易", "rule": "凌晨0:00-6:00频繁登录/交易", "risk": "低"},
    {"id": "B004", "name": "突然大额入金", "rule": "单笔入金超过历史平均5倍以上", "risk": "中"},
    {"id": "B005", "name": "分散转出", "rule": "单日出金至5个以上不同银行账户", "risk": "高"},
    {"id": "B006", "name": "产品风险越级", "rule": "要求购买超过风险等级2级以上的产品", "risk": "高"},
    {"id": "B007", "name": "信息频繁变更", "rule": "30天内变更手机/地址≥3次", "risk": "中"},
    {"id": "B008", "name": "代理操作", "rule": "频繁由同一非本人设备/IP操作", "risk": "高"},
]

BEHAVIOR_ABNORMAL_SCORE: Dict[str, int] = {
    "无异常": 20,
    "1-2项低风险": 15,
    "1-2项中风险": 10,
    "3项以上中风险": 5,
    "任何高风险": 0,
}

# ==================== 等级映射 ====================

RISK_LEVEL_MAPPING: List[Tuple[int, int, str, str]] = [
    # (min_score, max_score, level_code, level_name)
    (0, 25, "C1", "保守型"),
    (26, 40, "C2", "稳健型"),
    (41, 60, "C3", "平衡型"),
    (61, 80, "C4", "进取型"),
    (81, 100, "C5", "激进型"),
]

# ==================== 产品匹配矩阵 ====================

SUITABILITY_MATRIX: Dict[str, List[str]] = {
    "C1": ["R1", "R2"],
    "C2": ["R1", "R2", "R3"],
    "C3": ["R1", "R2", "R3", "R4"],   # R4需风险揭示书
    "C4": ["R1", "R2", "R3", "R4", "R5"],  # R5需风险揭示书
    "C5": ["R1", "R2", "R3", "R4", "R5"],
}

# ==================== 硬性熔断规则 ====================

CIRCUIT_BREAKER_RULES = [
    # FM-01: 年龄限制
    {
        "rule_id": "FM-01",
        "rule_name": "年龄限制",
        "conditions": [
            {"cond": "age < 18", "action": "禁止开户", "level": "block"},
            {"cond": "18 <= age <= 22", "action": "R4+需监护人知情同意书", "level": "restrict"},
            {"cond": "age > 70", "action": "R3+需网点面签确认", "level": "restrict"},
            {"cond": "age > 80", "action": "仅允许R1-R2，R3需特殊审批", "level": "restrict"},
        ],
    },
    # FM-02: 收入与资产限制
    {
        "rule_id": "FM-02",
        "rule_name": "收入与资产限制",
        "conditions": [
            {"cond": "no_income AND assets < 10000", "action": "仅允许R1-R2", "level": "restrict"},
            {"cond": "no_income AND 10000 <= assets <= 50000",
             "action": "R1-R3，R3持仓不超过总资产30%", "level": "restrict"},
        ],
    },
    # FM-03: 风评时效
    {
        "rule_id": "FM-03",
        "rule_name": "风评时效检查",
        "conditions": [
            {"cond": "days_since_risk_assessment > 365", "action": "冻结购买权限，仅允许赎回", "level": "block"},
            {"cond": "days_since_risk_assessment > 180", "action": "发送提醒通知，暂不限制交易", "level": "warn"},
        ],
    },
    # FM-04: 身份异常
    {
        "rule_id": "FM-04",
        "rule_name": "身份异常检查",
        "conditions": [
            {"cond": "id_expired_days > 90", "action": "冻结账户全部交易权限", "level": "block"},
            {"cond": "identity_check_failed", "action": "暂停非柜面交易，要求临柜核实", "level": "restrict"},
            {"cond": "sanction_list_match", "action": "立即冻结，上报合规部门", "level": "block"},
        ],
    },
    # FM-05: 异常交易熔断
    {
        "rule_id": "FM-05",
        "rule_name": "异常交易熔断",
        "conditions": [
            {"cond": "daily_loss > total_assets * 0.1", "action": "推送风险提示弹窗，建议暂停交易", "level": "warn"},
            {"cond": "consecutive_3day_redeem > total_assets * 0.4",
             "action": "触发人工回访，确认客户意愿", "level": "restrict"},
            {"cond": "account_theft_suspected", "action": "立即冻结账户，通知客户", "level": "block"},
        ],
    },
]

# ==================== 置信度配置 ====================

CONFIDENCE_SOURCE_INITIAL = {
    "questionnaire": 0.9,   # 风评问卷
    "ai_extract": 0.6,      # AI对话提取
    "self_report": 0.4,     # 用户自述
    "default": 0.2,         # 默认值
}

# ==================== 特殊场景配置 ====================

SPECIAL_POPULATION_RULES = {
    "在校学生": {"income_treatment": 0, "product_limit": ["R1", "R2"], "note": "无独立收入"},
    "失信被执行人": {"action": "限制大额申购，加强资金来源核实"},
    "外籍人士": {"action": "增加国籍/地区风险因子，高风险国家下调一档"},
}

SELF_VS_AI_CONFLICT = {
    "diff_1": "取AI评估结果，允许客户申请人工复核",
    "diff_2": "取AI评估结果，客户需到网点进行面对面评估",
    "diff_3+": "取AI评估结果，触发合规调查",
}

INCOMPLETE_INFO_RULES = {
    "收入缺失": "按当地最低工资标准估算，风险评级下调一档",
    "资产缺失": "仅依据已知金融资产评估，忽略房产等其他资产",
    "投资经验缺失": "投资经验维度默认3分（保守处理）",
    "联系方式失效": "限制非柜面交易，要求更新信息后方可恢复",
    "多项缺失(>3项)": "暂停新开户，要求客户补充完整信息",
}

# ==================== 资产配置模板 ====================

ASSET_ALLOCATION_TEMPLATES: Dict[str, Dict[str, float]] = {
    "C1": {"货币类": 0.40, "债券类": 0.40, "混合类": 0, "股票类": 0, "现金": 0.20},
    "C2": {"货币类": 0.20, "债券类": 0.50, "混合类": 0.20, "股票类": 0, "现金": 0.10},
    "C3": {"货币类": 0.10, "债券类": 0.35, "混合类": 0.30, "股票类": 0.20, "现金": 0.05},
    "C4": {"货币类": 0.05, "债券类": 0.20, "混合类": 0.30, "股票类": 0.40, "现金": 0.05},
    "C5": {"货币类": 0, "债券类": 0.10, "混合类": 0.25, "股票类": 0.55, "现金": 0.10},
}

# ==================== 推荐引擎配置 ====================

RECOMMENDATION_WEIGHTS = {
    "risk_match": 0.40,       # 风险匹配度
    "preference": 0.25,        # 偏好匹配度
    "diversification": 0.20,  # 持仓互补度
    "return_term": 0.15,      # 收益期限度
}

# ==================== 画像更新触发条件 ====================

PROFILE_UPDATE_TRIGGERS = {
    "定期触发": "风评到期前30天",
    "事件触发": "大额资金变动(>50万)",
    "行为触发": "交易行为模式显著变化",
    "市场触发": "指数波动>20%",
    "人工触发": "客户主动申请调整",
}

# ==================== 漂移检测配置 ====================

DRIFT_DETECTION_CONFIG = {
    "check_interval_days": 30,          # 每月检测一次
    "behavior_match_threshold": 0.60,   # 行为匹配度阈值
    "return_deviation_std": 2.0,        # 收益率偏离标准差
    "complaint_rate_multiplier": 2.0,   # 投诉率异常倍数
}
