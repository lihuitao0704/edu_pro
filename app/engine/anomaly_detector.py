"""
行为偏离检测器
基于客户历史交易统计量，计算当前交易的行为偏离分数
原理：跟自己过去比 —— 这笔交易有多不像这个人的日常行为
"""

import logging
import math

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """行为偏离检测器，输出 0~1 异常分数"""

    def __init__(self):
        pass

    @staticmethod
    def score(tx: dict, stats: dict, customer: dict) -> float:
        """
        综合计算行为偏离分数。
        tx:      当前交易 {amount, transaction_type, timestamp}
        stats:   历史统计 from fin_transaction
        customer: 客户画像 from sys_user
        返回: 0.0(完全正常) ~ 1.0(极度异常)
        """
        sub_scores = []

        # ── 1. 金额偏离 ──
        amount_score = _amount_deviation(tx.get("amount", 0), stats)
        sub_scores.append(("金额偏离", 0.30, amount_score))

        # ── 2. 频率偏离 ──
        freq_score = _frequency_spike(tx, stats)
        sub_scores.append(("频率飙升", 0.20, freq_score))

        # ── 3. 时段偏离 ──
        time_score = _time_deviation(tx, stats)
        sub_scores.append(("时段偏离", 0.15, time_score))

        # ── 4. 首次行为 ──
        novelty_score = _novelty_check(tx, stats)
        sub_scores.append(("首次行为", 0.20, novelty_score))

        # ── 5. 金额整数规避 ──
        pattern_score = _avoid_pattern(tx.get("amount", 0))
        sub_scores.append(("规避特征", 0.15, pattern_score))

        total = sum(weight * score for _, weight, score in sub_scores)
        return round(max(0.0, min(1.0, total)), 4)


def _amount_deviation(amount: float, stats: dict) -> float:
    """金额偏离历史均值的程度"""
    avg = float(stats.get("monthly_avg_12m", 0) or 0)
    if avg <= 0 or amount <= 0:
        return 0.0
    ratio = amount / avg
    if ratio <= 2:
        return 0.0        # 2 倍以内正常
    elif ratio <= 5:
        return 0.3        # 2~5 倍轻度关注
    elif ratio <= 10:
        return 0.6        # 5~10 倍显著异常
    elif ratio <= 50:
        return 0.85       # 10~50 倍高度异常
    return 1.0            # 50 倍以上极强异常


def _frequency_spike(tx: dict, stats: dict) -> float:
    """最近 7 天交易频率是否突然飙升"""
    weekly_count = int(stats.get("weekly_count", 0) or 0)
    amount = float(tx.get("amount", 0) or 0)
    if weekly_count <= 5:
        return 0.0
    if weekly_count <= 10:
        return 0.3
    if weekly_count <= 20:
        return 0.5 if amount > 50000 else 0.3
    return 0.8 if amount > 50000 else 0.5


def _time_deviation(tx: dict, stats: dict) -> float:
    """非正常时段交易"""
    ts = tx.get("timestamp", "")
    try:
        hour = int(ts[11:13]) if len(ts) >= 13 else 12
    except (ValueError, IndexError, TypeError):
        return 0.0
    if 22 <= hour or hour < 6:
        return 0.9  # 深夜
    if 6 <= hour < 8:
        return 0.3  # 清晨
    return 0.0


def _novelty_check(tx: dict, stats: dict) -> float:
    """首次出现的交易模式"""
    tx_type = tx.get("transaction_type", "")
    total_since_open = float(stats.get("total_since_open", 0) or 0)
    if total_since_open > 0:
        return 0.0
    # 新开户且首次交易就是大额
    amount = float(tx.get("amount", 0) or 0)
    if amount >= 100000:
        return 0.7
    if amount >= 50000:
        return 0.4
    return 0.1


def _avoid_pattern(amount: float) -> float:
    """检测刻意规避整数金额的特征"""
    if amount <= 0:
        return 0.0
    frac = amount - math.floor(amount)
    if amount >= 10000 and frac < 1:
        # 整万金额：如 50000、200000，正常
        return 0.0
    if amount >= 45000 and str(int(amount)).endswith("999"):
        # 49,999 / 199,999 等规避金额
        return 0.9
    return 0.0
