"""
客服侧风控信号检测规则
用于从客服对话中识别可疑风控信号，反向通知风控Agent

信号类型：
- account_compromise: 账户被盗/异常操作
- social_engineering: 社会工程学攻击
- abnormal_intent: 异常交易意图
- identity_failure: 身份验证失败
- behavior_change: 行为突变

检测层级：
- L1: 关键词规则（<1ms）
- L2: 行为模式（<5ms）
- L3: LLM辅助（~500ms）
"""

from typing import Optional
from dataclasses import dataclass


@dataclass
class RiskSignal:
    """风控信号"""
    signal_type: str  # account_compromise | social_engineering | abnormal_intent | identity_failure | behavior_change
    signal_level: str  # low | medium | high
    confidence: float  # 0.0 ~ 1.0
    keywords_hit: list[str]  # 命中的关键词
    evidence: dict  # 证据上下文


# ═══════════════════════════════════════════════════════════
# L1 关键词规则
# ═══════════════════════════════════════════════════════════

RISK_SIGNAL_RULES = {
    "account_compromise": {
        "keywords": [
            "账户被盗", "不是我操作的", "被人登录", "密码泄露",
            "异常登录", " unauthorized", "被盗刷", "账户异常",
            "有人动了我的账户", "非法操作", "账户被黑",
        ],
        "level": "high",
        "confidence": 0.6,
    },
    "social_engineering": {
        "keywords": [
            "我是XX领导", "内部人员", "帮我查一下别人", "bypass",
            "我是客服", "我是银行工作人员", "紧急处理", "特殊权限",
            "领导要求", "内部渠道", "后门",
        ],
        "level": "high",
        "confidence": 0.6,
    },
    "abnormal_intent": {
        "keywords": [
            "全部转出", "转到陌生账户", "不留余额", "清空账户",
            "紧急转账", "马上转", "立刻赎回", "全部提现",
            "转到新账户", "不认识的人", "陌生人",
        ],
        "level": "medium",
        "confidence": 0.6,
    },
    "identity_failure": {
        # 由行为计数器触发，非关键词
        "keywords": [],
        "level": "medium",
        "confidence": 0.7,
    },
    "behavior_change": {
        # 由行为模式检测触发
        "keywords": [],
        "level": "medium",
        "confidence": 0.7,
    },
}


# ═══════════════════════════════════════════════════════════
# L2 行为模式规则
# ═══════════════════════════════════════════════════════════

BEHAVIOR_PATTERNS = {
    # 同一客户短时间内多次触发敏感信号
    "frequent_sensitive_signals": {
        "description": "30分钟内触发≥3次L1信号",
        "threshold": 3,
        "time_window_minutes": 30,
        "upgrade_level": "high",
        "confidence": 0.8,
    },
    # 身份验证连续失败
    "identity_verification_failures": {
        "description": "连续3次身份验证失败",
        "threshold": 3,
        "time_window_minutes": 10,
        "upgrade_level": "high",
        "confidence": 0.85,
    },
    # 异常时间段操作（凌晨2-6点大额操作）
    "abnormal_time_operation": {
        "description": "凌晨2-6点大额操作",
        "time_range": (2, 6),
        "amount_threshold": 50000,
        "upgrade_level": "medium",
        "confidence": 0.7,
    },
}


# ═══════════════════════════════════════════════════════════
# L3 LLM辅助检测 Prompt
# ═══════════════════════════════════════════════════════════

LLM_SIGNAL_CLASSIFICATION_PROMPT = """你是一个风控信号分类专家。请分析以下客服对话内容，判断是否存在可疑的风控信号。

对话内容：
{conversation}

请判断是否存在以下类型的信号：
1. account_compromise: 账户被盗/异常操作（如"账户被盗"、"不是我操作的"）
2. social_engineering: 社会工程学攻击（如冒充内部人员、要求特殊权限）
3. abnormal_intent: 异常交易意图（如"全部转出"、"转到陌生账户"）
4. identity_failure: 身份验证失败（如多次输错验证码）
5. behavior_change: 行为突变（如长期低风险客户突然大额操作）

请以JSON格式返回：
{{
  "has_signal": true/false,
  "signal_type": "信号类型或null",
  "confidence": 0.0-1.0,
  "reason": "判断理由"
}}

如果无法确定，请返回 has_signal: false。
"""


def detect_l1_signals(message: str) -> list[RiskSignal]:
    """
    L1 关键词规则检测

    Args:
        message: 用户消息

    Returns:
        检测到的信号列表
    """
    signals = []
    message_lower = message.lower()

    for signal_type, rule in RISK_SIGNAL_RULES.items():
        keywords = rule.get("keywords", [])
        if not keywords:
            continue  # 跳过需要行为检测的类型

        hit_keywords = []
        for kw in keywords:
            if kw.lower() in message_lower:
                hit_keywords.append(kw)

        if hit_keywords:
            signals.append(RiskSignal(
                signal_type=signal_type,
                signal_level=rule["level"],
                confidence=rule["confidence"],
                keywords_hit=hit_keywords,
                evidence={"message": message[:200]},
            ))

    return signals


def should_trigger_l3_detection(l1_signals: list[RiskSignal], l2_triggered: bool) -> bool:
    """
    判断是否需要触发 L3 LLM 辅助检测

    触发条件：
    1. L1 检测到信号但置信度 < 0.7
    2. L2 行为模式触发但需要确认

    Args:
        l1_signals: L1 检测到的信号
        l2_triggered: L2 行为模式是否触发

    Returns:
        是否触发 L3 检测
    """
    # L1 有信号但置信度不高
    if l1_signals:
        max_confidence = max(s.confidence for s in l1_signals)
        if max_confidence < 0.7:
            return True

    # L2 触发但需要 LLM 确认上下文
    if l2_triggered:
        return True

    return False
