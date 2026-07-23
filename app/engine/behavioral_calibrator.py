"""
双轨校准引擎 —— "自评风险画像" vs "行为真实画像"

用交易行为数据反向校准客户自评，解决"问卷不准、客户乱填"的问题。
支持 7 条规则：

  CAL-01  恐慌赎回：持仓亏损 >5% 且 30 天内有赎回 → 自评偏乐观
  CAL-02  频繁改策略：90天内调仓 ≥3次 → 自评不可靠
  CAL-03  情绪化交易：检测到追涨杀跌/FOMO 行为 → 自评偏乐观
  CAL-04  交易频率偏差：自评低频但实际高频 → 自评偏保守
  CAL-05  亏损承受偏差：问卷说能扛但实际亏了就跑
  CAL-06  持仓保守：自评激进但持仓全是低风险产品
  CAL-07  风评过期仍激进：风评过期后仍进行R3+交易 → 自评偏乐观

输出方向：
  over_optimistic   — 自评偏乐观（说的比做的激进）
  over_conservative — 自评偏保守（做的比说的激进）
  aligned           — 自评与行为一致
"""

from typing import Optional, List, Dict
from dataclasses import dataclass, field
from datetime import datetime, date


@dataclass
class CalibrationResult:
    """校准结果"""
    calibrate_time: str = field(default_factory=lambda: datetime.now().isoformat())
    direction: str = "aligned"  # over_optimistic | over_conservative | aligned
    self_reported: dict = field(default_factory=dict)
    behavioral: dict = field(default_factory=dict)
    triggered_rules: list = field(default_factory=list)
    summary: str = ""


class BehavioralCalibrator:
    """行为校准器：对比自评数据 vs 实际交易行为"""

    # ═══════════════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════════════

    def calibrate(
        self, customer_data: dict, dimension_scores: Optional[dict] = None
    ) -> CalibrationResult:
        """
        执行双轨校准

        Args:
            customer_data: 客户全量数据（来自 ProfileService._collect_customer_data）
            dimension_scores: 四维度得分（可选，用于交叉验证）

        Returns:
            CalibrationResult 包含方向判定、自评画像、行为画像、触规则列表、摘要
        """
        result = CalibrationResult()

        # 1. 提取自评画像
        result.self_reported = self._extract_self_reported(customer_data)

        # 2. 逐条运行校准规则，收集证据
        evidence_optimistic = []
        evidence_conservative = []

        rule_methods = [
            self._check_panic_redeem,          # CAL-01 / CAL-05
            self._check_strategy_changes,      # CAL-02
            self._check_emotional_trading,     # CAL-03
            self._check_frequency_mismatch,    # CAL-04
            self._check_conservative_holdings, # CAL-06
            self._check_expired_risk_trading,  # CAL-07
        ]

        for rule_fn in rule_methods:
            triggered = rule_fn(customer_data, result.self_reported)
            if triggered:
                for rule in triggered:
                    result.triggered_rules.append(rule)
                    direction = rule.get("direction", "")
                    if direction == "over_optimistic":
                        evidence_optimistic.append(rule["detail"])
                    elif direction == "over_conservative":
                        evidence_conservative.append(rule["detail"])

        # 3. 推断行为画像
        result.behavioral = self._infer_behavioral_profile(
            customer_data, result.self_reported, evidence_optimistic, evidence_conservative
        )

        # 4. 判定方向
        if evidence_optimistic and evidence_conservative:
            if len(evidence_optimistic) >= len(evidence_conservative):
                result.direction = "over_optimistic"
            else:
                result.direction = "over_conservative"
        elif evidence_optimistic:
            result.direction = "over_optimistic"
        elif evidence_conservative:
            result.direction = "over_conservative"
        else:
            result.direction = "aligned"

        # 5. 生成摘要
        result.summary = self._build_summary(result)

        return result

    # ═══════════════════════════════════════════════════════════
    # 自评数据提取
    # ═══════════════════════════════════════════════════════════

    def _extract_self_reported(self, data: dict) -> dict:
        return {
            "loss_tolerance": data.get("loss_tolerance") or "10%-20%",
            "risk_level": data.get("risk_assessment_level") or data.get("self_assessment_level") or "C3",
            "investment_years": data.get("investment_years") or "1-3年",
            "max_product_type": data.get("max_product_type") or "仅银行存款",
            "trade_frequency": data.get("self_stated_frequency") or data.get("trade_frequency") or "低频",
        }

    # ═══════════════════════════════════════════════════════════
    # CAL-01 / CAL-05: 恐慌赎回 + 亏损承受偏差
    # ═══════════════════════════════════════════════════════════

    def _check_panic_redeem(
        self, data: dict, self_reported: dict
    ) -> List[dict]:
        """
        CAL-01: 持仓浮亏 + 近期赎回 → 恐慌赎回
        CAL-05: 自评能扛大亏损 但实际小亏就跑 → 亏损承受偏差
        """
        has_losing = data.get("has_losing_holdings", False)
        has_redeems = data.get("has_recent_redeems", False)
        loss_tolerance = self_reported.get("loss_tolerance", "10%-20%")

        # 增强证据详情（如果可用）
        losing_details = data.get("losing_holdings_detail", [])
        redeem_details = data.get("recent_redeems_detail", [])
        max_loss_pct = data.get("max_losing_pct", 0)

        triggered = []

        # CAL-01: 持仓浮亏 + 近期赎回 → 恐慌赎回
        if has_losing and has_redeems:
            evidence = {
                "has_losing_holdings": True,
                "has_recent_redeems": True,
                "losing_holding_count": len(losing_details),
                "redeem_count_30d": len(redeem_details),
            }
            if losing_details:
                evidence["losing_holdings"] = losing_details[:5]  # 最多5条
            if redeem_details:
                evidence["recent_redeems"] = redeem_details[:5]
            if max_loss_pct:
                evidence["max_loss_pct"] = max_loss_pct

            triggered.append({
                "rule_id": "CAL-01",
                "rule_name": "恐慌赎回检测",
                "direction": "over_optimistic",
                "detail": "客户在持仓浮亏超过5%的情况下仍有赎回操作，表现出对亏损的敏感度高于预期",
                "evidence": evidence,
            })

        # CAL-05: 自评能扛大亏损 但实际小亏就跑
        if triggered and loss_tolerance in ("20%-40%", "40%以上"):
            triggered.append({
                "rule_id": "CAL-05",
                "rule_name": "亏损承受偏差",
                "direction": "over_optimistic",
                "detail": f"客户自评可承受'{loss_tolerance}'亏损，但实际持仓浮亏时已出现赎回行为，自评偏乐观",
                "evidence": {
                    "self_reported_tolerance": loss_tolerance,
                    "actual_behavior": "浮亏时赎回",
                    "max_losing_pct": max_loss_pct,
                },
            })

        return triggered

    # ═══════════════════════════════════════════════════════════
    # CAL-02: 频繁策略变更
    # ═══════════════════════════════════════════════════════════

    def _check_strategy_changes(
        self, data: dict, self_reported: dict
    ) -> List[dict]:
        """
        CAL-02: 90天内调整投资组合配置超过3次 → 自评不稳定、不可靠
        模式：声称"长期投资"但频繁调仓，说明对自身风险认知不稳定
        """
        strategy_changes = data.get("strategy_change_count", 0)
        if strategy_changes <= 3:
            return []

        change_dates = data.get("strategy_change_dates", [])
        allocation_changes = data.get("strategy_allocation_changes", [])

        return [{
            "rule_id": "CAL-02",
            "rule_name": "频繁策略变更",
            "direction": "over_optimistic",
            "detail": f"客户近90天调整投资策略/组合配置{strategy_changes}次（合理阈值≤3次），"
                      f"频繁改变投资方向表明其自评风险偏好不够稳定，不宜作为唯一依据",
            "evidence": {
                "strategy_change_count": strategy_changes,
                "threshold": 3,
                "window_days": 90,
                "change_dates": change_dates[:10],
                "allocation_changes": [
                    {"from": c.get("from_allocation", ""), "to": c.get("to_allocation", ""),
                     "date": c.get("date", "")}
                    for c in allocation_changes[:5]
                ],
            },
        }]

    # ═══════════════════════════════════════════════════════════
    # CAL-03: 情绪化交易检测
    # ═══════════════════════════════════════════════════════════

    def _check_emotional_trading(
        self, data: dict, self_reported: dict
    ) -> List[dict]:
        """
        CAL-03: 检测追涨杀跌/FOMO/恐慌抛售等情绪驱动交易模式
        数据来源：维度三中的 emotional_triggers + 交易行为数据
        """
        emotional_patterns = data.get("emotional_trading_patterns", [])
        if not emotional_patterns:
            return []

        pattern_desc = {
            "buy_at_peak": "净值新高后3日内买入（追涨）",
            "sell_at_trough": "净值新低后3日内卖出（杀跌）",
            "fomo_large_buy": "连续3日上涨后大额加仓（FOMO）",
            "panic_sell": "单日亏损超过总资产10%后立即赎回（恐慌抛售）",
        }

        pattern_details = []
        for pattern in emotional_patterns:
            detail = {
                "type": pattern,
                "description": pattern_desc.get(pattern, pattern),
                "occurrence_count_90d": data.get(f"emotional_count_{pattern}", 0),
                "sample_transactions": data.get(f"emotional_sample_{pattern}", [])[:3],
            }
            pattern_details.append(detail)

        return [{
            "rule_id": "CAL-03",
            "rule_name": "情绪化交易检测",
            "direction": "over_optimistic",
            "detail": f"检测到{len(emotional_patterns)}种情绪化交易模式："
                      f"{'、'.join(pattern_desc.get(p, p) for p in emotional_patterns)}。"
                      f"客户交易决策受情绪影响显著，自评不适合作为唯一风险参考依据",
            "evidence": {
                "patterns": pattern_details,
                "total_patterns": len(emotional_patterns),
            },
        }]

    # ═══════════════════════════════════════════════════════════
    # CAL-04: 交易频率偏差
    # ═══════════════════════════════════════════════════════════

    def _check_frequency_mismatch(
        self, data: dict, self_reported: dict
    ) -> List[dict]:
        """
        CAL-04: 问卷/自评声称"低频交易"但实际操作高频 → 自评偏保守
        实际交易活跃度远超自述，说明客户比声称的更愿意承担风险
        """
        stated_freq = self_reported.get("trade_frequency") or data.get("self_stated_frequency", "")
        actual_freq = data.get("trade_frequency", "")
        actual_count = data.get("trade_count_365d", 0)

        if not stated_freq or not actual_freq:
            return []

        freq_level = {"极低频": 1, "低频": 2, "中频": 3, "高频": 4}
        stated_level = freq_level.get(stated_freq, 2)
        actual_level = freq_level.get(actual_freq, 2)

        # 差值 ≥ 2 级才触发（如：声称低频(2)→实际高频(4)）
        if actual_level - stated_level < 2:
            return []

        return [{
            "rule_id": "CAL-04",
            "rule_name": "交易频率偏差",
            "direction": "over_conservative",
            "detail": f"客户自述交易频率'{stated_freq}'（年交易约<36笔），"
                      f"但实际近一年交易{actual_count}笔（判定为{actual_freq}），"
                      f"实际操作远比声称的活跃，自评偏保守",
            "evidence": {
                "self_reported_frequency": stated_freq,
                "actual_trade_count_365d": actual_count,
                "actual_frequency": actual_freq,
                "frequency_gap": actual_level - stated_level,
            },
        }]

    # ═══════════════════════════════════════════════════════════
    # CAL-06: 自评激进但持仓保守
    # ═══════════════════════════════════════════════════════════

    def _check_conservative_holdings(
        self, data: dict, self_reported: dict
    ) -> List[dict]:
        """
        自评风险等级为 C4/C5，但实际持仓最高风险产品仅为 R1-R2
        """
        risk_level = self_reported.get("risk_level", "C3")
        max_product = self_reported.get("max_product_type", "")

        if risk_level not in ("C4", "C5"):
            return []

        conservative_types = [
            "仅银行存款", "货币基金/国债", "纯债基金/银行理财(R1-R2)",
        ]
        if max_product in conservative_types:
            # 增强证据：展示实际持仓明细
            holding_summary = data.get("holding_product_summary", [])
            return [{
                "rule_id": "CAL-06",
                "rule_name": "持仓保守偏差",
                "direction": "over_conservative",
                "detail": f"客户自评风险等级为{risk_level}进取型，但实际持仓最高仅为'{max_product}'，"
                          f"实际行为比声称的更保守",
                "evidence": {
                    "self_reported_level": risk_level,
                    "actual_max_product": max_product,
                    "holding_summary": holding_summary[:5],
                },
            }]

        return []

    # ═══════════════════════════════════════════════════════════
    # CAL-07: 风评过期后依然激进交易
    # ═══════════════════════════════════════════════════════════

    def _check_expired_risk_trading(
        self, data: dict, self_reported: dict
    ) -> List[dict]:
        """
        CAL-07: 风评已过期但仍进行R3+等级交易 → 自评偏乐观
        无视风评提醒，说明对风险缺乏敬畏
        """
        risk_valid_until = data.get("risk_valid_until")
        if not risk_valid_until:
            return []

        if isinstance(risk_valid_until, str):
            try:
                risk_valid_until = date.fromisoformat(risk_valid_until)
            except (ValueError, TypeError):
                return []

        days_expired = (date.today() - risk_valid_until).days
        if days_expired <= 30:  # 过期30天内给予缓冲期
            return []

        risky_trades = data.get("expired_risky_trades", [])
        if not risky_trades:
            return []

        return [{
            "rule_id": "CAL-07",
            "rule_name": "风评过期激进交易",
            "direction": "over_optimistic",
            "detail": f"风评已于{risk_valid_until.isoformat()}过期（{days_expired}天），"
                      f"但客户在此期间仍进行了{len(risky_trades)}笔R3+等级交易，"
                      f"对风险提示缺乏应有重视",
            "evidence": {
                "risk_expiry_date": risk_valid_until.isoformat(),
                "days_expired": days_expired,
                "risky_trade_count": len(risky_trades),
                "risky_transactions": [
                    {"transaction_id": t.get("transaction_id", t.get("id", "")),
                     "product_level": t.get("product_level", t.get("level", "")),
                     "amount": t.get("amount", 0),
                     "date": t.get("date", str(t.get("create_time", "")))}
                    for t in risky_trades[:5]
                ],
            },
        }]

    # ═══════════════════════════════════════════════════════════
    # 行为画像推断
    # ═══════════════════════════════════════════════════════════

    def _infer_behavioral_profile(
        self,
        data: dict,
        self_reported: dict,
        evidence_optimistic: list,
        evidence_conservative: list,
    ) -> dict:
        """
        基于行为数据推断"真实画像"
        - 恐慌赎回 / 情绪化交易 → 降低有效亏损承受
        - 持仓保守 → 降低有效风险等级
        - 交易频率高于自评 → 提升有效风险等级
        """
        loss_tolerance = self_reported.get("loss_tolerance", "10%-20%")
        risk_level = self_reported.get("risk_level", "C3")

        # 有效亏损承受
        if evidence_optimistic:
            downgrade = {
                "不能承受任何亏损": "不能承受任何亏损",
                "5%以内": "不能承受任何亏损",
                "10%-20%": "5%以内",
                "20%-40%": "10%-20%",
                "40%以上": "20%-40%",
            }
            effective_loss = downgrade.get(loss_tolerance, "5%以内")
        else:
            effective_loss = loss_tolerance

        # 有效风险等级
        # evidence_conservative → 行为说明客户比自评更活跃 → 上调
        # evidence_optimistic → 行为说明客户比自评更胆小 → 下调
        if evidence_conservative and evidence_optimistic:
            # 矛盾信号：取两者较多的方向
            if len(evidence_conservative) > len(evidence_optimistic):
                upgrade = {"C1": "C2", "C2": "C3", "C3": "C4", "C4": "C5", "C5": "C5"}
                effective_level = upgrade.get(risk_level, risk_level)
            else:
                downgrade_level = {"C1": "C1", "C2": "C1", "C3": "C2", "C4": "C3", "C5": "C4"}
                effective_level = downgrade_level.get(risk_level, risk_level)
        elif evidence_conservative:
            upgrade = {"C1": "C2", "C2": "C3", "C3": "C4", "C4": "C5", "C5": "C5"}
            effective_level = upgrade.get(risk_level, risk_level)
        elif evidence_optimistic:
            downgrade_level = {"C1": "C1", "C2": "C1", "C3": "C2", "C4": "C3", "C5": "C4"}
            effective_level = downgrade_level.get(risk_level, risk_level)
        else:
            effective_level = risk_level

        return {
            "effective_loss_tolerance": effective_loss,
            "effective_risk_level": effective_level,
            "optimistic_evidence_count": len(evidence_optimistic),
            "conservative_evidence_count": len(evidence_conservative),
        }

    # ═══════════════════════════════════════════════════════════
    # 摘要生成
    # ═══════════════════════════════════════════════════════════

    def _build_summary(self, result: CalibrationResult) -> str:
        if result.direction == "aligned":
            return "客户自评风险偏好与实际交易行为基本一致，未检测到显著偏差。"

        parts = []
        for rule in result.triggered_rules:
            parts.append(f"[{rule.get('rule_id', '')}] {rule.get('detail', '')}")

        prefix = {
            "over_optimistic": "【自评偏乐观】客户自述风险承受能力高于实际行为表现：",
            "over_conservative": "【自评偏保守】客户自述偏保守，但实际行为显示其风险承受能力更强：",
        }.get(result.direction, "")

        # 追加行为画像推断
        behavioral = result.behavioral
        suffix = (
            f" → 有效亏损承受={behavioral.get('effective_loss_tolerance', 'N/A')}，"
            f"有效风险等级={behavioral.get('effective_risk_level', 'N/A')}"
        )

        return prefix + "；".join(parts) + suffix


# ══════════════════════════════════════════════════════════════
# 单元测试（独立运行）
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    print("=" * 65)
    print("  双轨校准引擎 —— 独立单元测试")
    print("=" * 65)

    calibrator = BehavioralCalibrator()
    all_ok = True

    def check(name, actual, expected):
        global all_ok
        if actual == expected:
            print(f"  [PASS] {name}: {actual}")
        else:
            print(f"  [FAIL] {name}: 期望 {expected}, 实际 {actual}")
            all_ok = False

    # ── 测试1: aligned（无异常行为） ──
    print("\n[TEST 1] 正常客户 → aligned")
    normal = {
        "age": 35, "risk_assessment_level": "C3",
        "loss_tolerance": "10%-20%", "investment_years": "5-10年",
        "max_product_type": "混合基金/指数基金(R3)",
        "trade_frequency": "中频",
        "has_losing_holdings": False, "has_recent_redeems": False,
        "strategy_change_count": 0, "emotional_trading_patterns": [],
        "trade_count_365d": 24, "expired_risky_trades": [],
        "losing_holdings_detail": [], "recent_redeems_detail": [],
        "holding_product_summary": [],
    }
    r1 = calibrator.calibrate(normal)
    check("  方向", r1.direction, "aligned")
    check("  触规则数", len(r1.triggered_rules), 0)

    # ── 测试2: CAL-01 恐慌赎回 ──
    print("\n[TEST 2] 持仓浮亏 + 近期赎回 → CAL-01")
    panic = {**normal, "has_losing_holdings": True, "has_recent_redeems": True,
             "losing_holdings_detail": [
                 {"holding_id": 1, "product_name": "XX基金", "profit_ratio": -0.08, "current_value": 50000}
             ],
             "recent_redeems_detail": [
                 {"transaction_id": "T001", "amount": 20000, "date": "2026-07-15"}
             ],
             "max_losing_pct": -0.12}
    r2 = calibrator.calibrate(panic)
    check("  方向", r2.direction, "over_optimistic")
    cal01_triggered = any(r["rule_id"] == "CAL-01" for r in r2.triggered_rules)
    check("  CAL-01触发", cal01_triggered, True)

    # ── 测试3: CAL-05 亏损承受偏差 ──
    print("\n[TEST 3] 自评高承受 + 恐慌赎回 → CAL-05")
    high_tol = {**panic, "loss_tolerance": "20%-40%"}
    r3 = calibrator.calibrate(high_tol)
    cal05_triggered = any(r["rule_id"] == "CAL-05" for r in r3.triggered_rules)
    check("  CAL-05触发", cal05_triggered, True)

    # ── 测试4: CAL-02 频繁策略变更 ──
    print("\n[TEST 4] 90天调仓5次 → CAL-02")
    freq_change = {**normal, "strategy_change_count": 5,
                   "strategy_change_dates": ["2026-06-01", "2026-06-15", "2026-07-01", "2026-07-10", "2026-07-20"]}
    r4 = calibrator.calibrate(freq_change)
    cal02_triggered = any(r["rule_id"] == "CAL-02" for r in r4.triggered_rules)
    check("  CAL-02触发", cal02_triggered, True)

    # ── 测试5: CAL-03 情绪化交易 ──
    print("\n[TEST 5] 追涨杀跌模式 → CAL-03")
    emotional = {**normal,
                 "emotional_trading_patterns": ["buy_at_peak", "fomo_large_buy"],
                 "emotional_count_buy_at_peak": 3,
                 "emotional_count_fomo_large_buy": 2,
                 "emotional_sample_buy_at_peak": [{"id": "T101", "date": "2026-07-01"}],
                 "emotional_sample_fomo_large_buy": [{"id": "T102", "date": "2026-07-05"}]}
    r5 = calibrator.calibrate(emotional)
    cal03_triggered = any(r["rule_id"] == "CAL-03" for r in r5.triggered_rules)
    check("  CAL-03触发", cal03_triggered, True)

    # ── 测试6: CAL-04 交易频率偏差 ──
    print("\n[TEST 6] 自评低频→实际高频 → CAL-04")
    freq_mismatch = {**normal,
                     "trade_frequency": "高频", "self_stated_frequency": "低频",
                     "trade_count_365d": 150}
    r6 = calibrator.calibrate(freq_mismatch)
    cal04_triggered = any(r["rule_id"] == "CAL-04" for r in r6.triggered_rules)
    check("  CAL-04触发", cal04_triggered, True)
    check("  方向", r6.direction, "over_conservative")

    # ── 测试7: CAL-06 持仓保守 ──
    print("\n[TEST 7] 自评C4但仅持有R1 → CAL-06")
    conservative = {**normal,
                    "risk_assessment_level": "C4",
                    "max_product_type": "纯债基金/银行理财(R1-R2)"}
    r7 = calibrator.calibrate(conservative)
    cal06_triggered = any(r["rule_id"] == "CAL-06" for r in r7.triggered_rules)
    check("  CAL-06触发", cal06_triggered, True)
    check("  方向", r7.direction, "over_conservative")

    # ── 测试8: CAL-07 风评过期激进交易 ──
    print("\n[TEST 8] 风评过期+大额交易 → CAL-07")
    expired = {**normal,
               "risk_valid_until": "2026-01-01",
               "expired_risky_trades": [
                   {"transaction_id": "T201", "product_level": "R4", "amount": 100000, "date": "2026-07-20"}
               ]}
    r8 = calibrator.calibrate(expired)
    cal07_triggered = any(r["rule_id"] == "CAL-07" for r in r8.triggered_rules)
    check("  CAL-07触发", cal07_triggered, True)

    # ── 测试9: 混合信号（乐观+保守共存） ──
    print("\n[TEST 9] 混合信号 → 证据多的一方获胜")
    mixed = {**normal,
             "has_losing_holdings": True, "has_recent_redeems": True,
             "strategy_change_count": 5,
             "risk_assessment_level": "C4",
             "max_product_type": "純债基金/银行理财(R1-R2)"}
    r9 = calibrator.calibrate(mixed)
    # 乐观=2(CAL-01+CAL-02) vs 保守=1(CAL-06) → over_optimistic
    check("  方向", r9.direction, "over_optimistic")
    check("  总触规则数", len(r9.triggered_rules), 3)

    # ── 测试10: 行为画像推断 ──
    print("\n[TEST 10] 行为画像推断验证")
    # 有恐慌赎回 → 有效亏损承受应降档
    r2_behavioral = r2.behavioral
    check("  有效亏损承受≠自评", r2_behavioral["effective_loss_tolerance"] != "10%-20%", True)

    # ── 汇总 ──
    print(f"\n{'=' * 65}")
    if all_ok:
        print("  === ALL TESTS PASSED ===")
    else:
        print("  === SOME TESTS FAILED ===")
    print(f"{'=' * 65}\n")
