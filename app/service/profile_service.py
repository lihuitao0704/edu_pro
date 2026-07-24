"""
画像业务编排服务
画像创建 / 查询（Cache-Aside） / 增量更新 / 完整研判
"""

from typing import Optional, List
from datetime import datetime, date
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func
from app.model.entities import (
    FinCustomerProfile, CustomerTag, SysUser, RiskAssessment,
    FinHoldings, FinProduct, FinTransaction, FinRiskAlert, BizWorkOrder,
)
from app.model.schemas import ProfileResult, DimensionScore, DimensionDetail, CalibrationInfo
from app.engine.dimension_calculator import DimensionCalculator
from app.engine.circuit_breaker import CircuitBreaker
from app.engine.special_case import SpecialCaseHandler
from app.engine.confidence import ConfidenceCalculator
from app.engine.behavioral_calibrator import BehavioralCalibrator
from app.engine.score_mapper import (
    map_score_to_risk_level, calc_total_score, get_suitable_products,
)
from app.config.rules_config import (
    PRODUCT_COMPLEXITY_SCORE, TRADE_FREQUENCY_SCORE,
    HISTORICAL_RETURN_SCORE, LOSS_TOLERANCE_ADJUSTMENT,
)
from app.memory.profile_cache import ProfileCache
from app.memory.long_term import LongTermMemory
from app.utils.exceptions import ProfileNotFound, CircuitBreakerTriggered

PROFILE_CACHE_SCHEMA_VERSION = 2


class ProfileService:
    """画像业务服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.cache = ProfileCache()
        self.calculator = DimensionCalculator()
        self.breaker = CircuitBreaker()
        self.special = SpecialCaseHandler()
        self.confidence = ConfidenceCalculator()
        self.long_term = LongTermMemory(db)

    # ========== 画像查询（Cache-Aside） ==========

    async def get_profile(self, customer_id: int) -> Optional[FinCustomerProfile]:
        """查询画像（先 Redis → 后 MySQL → 回填缓存）"""
        cached = await self.cache.get(customer_id)
        if cached and cached.get("_schema_version") == PROFILE_CACHE_SCHEMA_VERSION:
            profile_data = {
                key: value
                for key, value in cached.items()
                if key != "_schema_version"
            }
            return FinCustomerProfile(**profile_data)

        stmt = select(FinCustomerProfile).where(FinCustomerProfile.customer_id == customer_id)
        result = await self.db.execute(stmt)
        profile = result.scalar_one_or_none()

        if profile:
            profile_dict = self._profile_to_dict(profile)
            await self.cache.set(customer_id, profile_dict)

        return profile

    # ========== 完整研判（核心） ==========

    async def assess(self, customer_id: int, trigger_type: str = "manual") -> ProfileResult:
        """执行完整画像研判打分"""
        # 1. 收集客户数据
        customer_data = await self._collect_customer_data(customer_id)
        if not customer_data:
            raise ProfileNotFound(customer_id)

        # 2. 硬性熔断检查
        cb_result = self.breaker.check_all(customer_data)

        # 3. 四维度打分
        dimension_scores = self.calculator.calc_all(customer_data)

        # 4. 综合评分
        scores_for_total = {k: v["score"] for k, v in dimension_scores.items()}
        total_score = calc_total_score(scores_for_total)
        ai_level, ai_level_name = map_score_to_risk_level(total_score)

        # 5. 特殊场景处理
        special_result = self.special.handle(customer_data, ai_level)

        # 6. 决定最终等级（保守处理：熔断和特殊场景可能导致降级）
        final_level = ai_level

        # 熔断产品限制
        blocked = cb_result.blocked_levels + special_result.product_restrictions
        suitable = get_suitable_products(final_level)
        if blocked:
            suitable = [p for p in suitable if p not in blocked]

        # 7. 更新画像
        await self._update_profile_after_assess(customer_id, final_level, int(total_score), dimension_scores)

        # 8. 归档记录
        cb_list = [{"rule_id": r.get("rule_id", ""), "detail": r.get("detail", "")} for r in cb_result.triggered_rules]
        await self.long_term.archive_rating_record(
            customer_id, dimension_scores, total_score, final_level, cb_list, trigger_type
        )

        # 8. 双轨校准：自评画像 vs 行为真实画像
        calibrator = BehavioralCalibrator()
        calibration_result = calibrator.calibrate(customer_data, dimension_scores)

        calibration_info = CalibrationInfo(
            calibrate_time=datetime.now(),
            direction=calibration_result.direction,
            self_reported=calibration_result.self_reported,
            behavioral=calibration_result.behavioral,
            triggered_rules=calibration_result.triggered_rules,
            summary=calibration_result.summary,
        )

        # 8a. 持久化校准记录
        await self._persist_calibration(customer_id, calibration_info, trigger_type)

        # 9. 返回结果
        warnings = cb_result.warnings + special_result.adjustments
        return ProfileResult(
            customer_id=customer_id,
            risk_level=final_level,
            risk_score=int(total_score),
            total_score=total_score,
            dimensions={
                "basic": DimensionScore(**dimension_scores["basic"]),
                "experience": DimensionScore(**dimension_scores["experience"]),
                "risk_pref": DimensionScore(**dimension_scores["risk_pref"]),
                "behavior": DimensionScore(**dimension_scores["behavior"]),
            },
            confidence_score=self.confidence.calc_single("ai_extract"),
            circuit_breakers=cb_list,
            warnings=warnings,
            recommended_products=suitable,
            calibration=calibration_info,
        )

    # ========== 标签更新 ==========

    async def update_tags(self, customer_id: int, tags: List[dict]) -> dict:
        """增量更新画像标签"""
        for tag in tags:
            # 查询旧标签
            stmt = select(CustomerTag).where(
                CustomerTag.customer_id == customer_id,
                CustomerTag.tag_name == tag["tag_name"],
            )
            result = await self.db.execute(stmt)
            old_tag = result.scalar_one_or_none()

            if old_tag:
                # 冲突处理
                winning, conflict = self.confidence.resolve_conflict(tag, {
                    "tag_name": old_tag.tag_name,
                    "tag_value": old_tag.tag_value,
                    "source": old_tag.source,
                })
                if conflict:
                    # 冲突则更新为新标签（如果新标签胜出）
                    if winning is tag or (isinstance(winning, dict) and winning.get("tag_name") == tag.get("tag_name")):
                        old_tag.tag_value = tag["tag_value"]
                        old_tag.source = tag.get("source", old_tag.source)
                        old_tag.confidence = self.confidence.calc_single(tag.get("source", "default"))
                        old_tag.update_time = datetime.now()
                else:
                    old_tag.tag_value = tag["tag_value"]
                    old_tag.source = tag.get("source", old_tag.source)
                    old_tag.update_time = datetime.now()
            else:
                # 新标签
                new_tag = CustomerTag(
                    customer_id=customer_id,
                    tag_name=tag["tag_name"],
                    tag_value=tag["tag_value"],
                    source=tag.get("source", "ai_extract"),
                    confidence=self.confidence.calc_single(tag.get("source", "ai_extract")),
                )
                self.db.add(new_tag)

        await self.db.flush()
        # 失效缓存
        await self.cache.invalidate(customer_id)
        return {"customer_id": customer_id, "updated_tags": len(tags)}

    # ========== 内部辅助 ==========

    async def _collect_customer_data(self, customer_id: int) -> Optional[dict]:
        """收集客户全量数据（所有字段从数据库动态计算）"""
        # 用户基础信息
        user_stmt = select(SysUser).where(SysUser.id == customer_id)
        user_result = await self.db.execute(user_stmt)
        user = user_result.scalar_one_or_none()
        if not user:
            return None

        # 已有的画像
        profile_stmt = select(FinCustomerProfile).where(FinCustomerProfile.customer_id == customer_id)
        profile_result = await self.db.execute(profile_stmt)
        profile = profile_result.scalar_one_or_none()

        # 最近风评
        ra_stmt = select(RiskAssessment).where(
            RiskAssessment.customer_id == customer_id
        ).order_by(RiskAssessment.create_time.desc()).limit(1)
        ra_result = await self.db.execute(ra_stmt)
        risk_assessment = ra_result.scalar_one_or_none()

        # ── 动态计算字段 ──
        max_product_type = await self._calc_max_product_type(customer_id)
        trade_frequency = await self._calc_trade_frequency(customer_id)
        historical_return = await self._calc_historical_return(customer_id)
        loss_tolerance = await self._calc_loss_tolerance(risk_assessment)

        return {
            "age": user.age,
            "education": user.education,
            "occupation": user.occupation,
            "annual_income_range": profile.annual_income_range if profile else None,
            "asset_range": self._map_asset_to_range(profile.total_assets) if profile else None,
            "total_assets": float(profile.total_assets) if profile and profile.total_assets else 0,
            "has_income": bool(profile and profile.annual_income_range),
            "investment_years": profile.investment_experience if profile else None,
            "risk_assessment_level": risk_assessment.risk_level if risk_assessment else None,
            "risk_valid_until": risk_assessment.valid_until if risk_assessment else None,
            # 以下字段从数据库动态计算
            "max_product_type": max_product_type,
            "trade_frequency": trade_frequency,
            "historical_return": historical_return,
            "loss_tolerance": loss_tolerance,
            # ── FM-03/FM-04/FM-05 熔断数据（从数据库动态计算，不再硬编码）──
            "abnormal_behaviors": await self._calc_abnormal_behaviors(customer_id),
            "is_student": user.occupation == "在校学生",
            "is_dishonest": await self._calc_is_dishonest(customer_id),
            "is_foreign": await self._calc_is_foreign(user),
            "id_expired_days": self._calc_id_expired_days(user),
            "identity_check_failed": await self._calc_identity_check_failed(user),
            "on_sanction_list": await self._calc_on_sanction_list(customer_id, profile),
            "daily_loss_pct": await self._calc_daily_loss_pct(customer_id, profile),
            "consecutive_redeem_pct": await self._calc_consecutive_redeem_pct(customer_id, profile),
            "account_theft_suspected": await self._calc_account_theft_suspected(customer_id),
            "self_assessment_level": risk_assessment.risk_level if risk_assessment else None,
            # ── 双轨校准所需行为数据（从真实表动态计算）──
            "has_losing_holdings": await self._calc_has_losing_holdings(customer_id),
            "has_recent_redeems": await self._calc_has_recent_redeems(customer_id),
            "losing_holdings_detail": await self._calc_losing_holdings_detail(customer_id),
            "recent_redeems_detail": await self._calc_recent_redeems_detail(customer_id),
            "max_losing_pct": await self._calc_max_losing_pct(customer_id),
            "strategy_change_count": await self._calc_strategy_changes_90d(customer_id),
            "strategy_change_dates": await self._calc_strategy_change_dates(customer_id),
            "strategy_allocation_changes": await self._calc_allocation_changes(customer_id),
            "emotional_trading_patterns": await self._calc_emotional_patterns(customer_id),
            "trade_count_365d": await self._calc_trade_count_365d(customer_id),
            "self_stated_frequency": await self._calc_self_stated_frequency(risk_assessment),
            "expired_risky_trades": await self._calc_expired_risky_trades(customer_id, risk_assessment),
            "holding_product_summary": await self._calc_holding_product_summary(customer_id),
        }

    # ── 动态计算辅助方法 ──────────────────────────────────────

    async def _calc_max_product_type(self, customer_id: int) -> str:
        """从持仓产品中取最高风险等级的产品类型（用于维度二复杂度评分）"""
        stmt = (
            select(FinProduct)
            .join(FinHoldings, FinHoldings.product_id == FinProduct.id)
            .where(
                FinHoldings.customer_id == customer_id,
                FinHoldings.status == "持有中",
            )
        )
        result = await self.db.execute(stmt)
        products = result.scalars().all()

        if not products:
            return "仅银行存款"  # 无持仓，保守默认

        # 按 risk_level 排序找最高风险产品
        risk_order = {"R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}
        highest = max(products, key=lambda p: risk_order.get(p.risk_level, 0))

        # 映射到复杂度评分表中的 key
        product_type = highest.product_type or ""
        if "股票" in product_type or "ETF" in product_type:
            return "股票/股票基金/ETF(R4)"
        elif "混合" in product_type:
            return "混合基金/指数基金(R3)"
        elif "债券" in product_type:
            return "纯债基金/银行理财(R1-R2)"
        elif "货币" in product_type:
            return "货币基金/国债"
        elif "期货" in product_type or "期权" in product_type or "私募" in product_type:
            return "期货/期权/私募/结构化产品(R5)"
        return "仅银行存款"

    async def _calc_trade_frequency(self, customer_id: int) -> str:
        """统计近一年交易频率"""
        from datetime import timedelta
        one_year_ago = datetime.now() - timedelta(days=365)
        stmt = select(func.count(FinTransaction.id)).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time >= one_year_ago,
        )
        result = await self.db.execute(stmt)
        count = result.scalar() or 0

        if count < 10:
            return "极低频"
        elif count < 36:  # 月均 < 3
            return "低频"
        elif count < 120:  # 月均 < 10
            return "中频"
        else:
            return "高频"

    async def _calc_historical_return(self, customer_id: int) -> str:
        """从持仓盈亏计算历史收益水平"""
        stmt = select(
            func.sum(FinHoldings.current_value).label("total_value"),
            func.sum(FinHoldings.profit_loss).label("total_pl"),
        ).where(
            FinHoldings.customer_id == customer_id,
            FinHoldings.status == "持有中",
        )
        result = await self.db.execute(stmt)
        row = result.one_or_none()
        if not row or not row.total_value or float(row.total_value) == 0:
            return "无历史记录"

        total_value = float(row.total_value)
        total_pl = float(row.total_pl or 0)
        rate = total_pl / (total_value - total_pl) if (total_value - total_pl) > 0 else 0

        if rate < -0.15:
            return "<-15%"
        elif -0.15 <= rate < -0.05:
            return "-15%~-5%"
        elif -0.05 <= rate < 0.05:
            return "-5%~5%"
        elif 0.05 <= rate < 0.15:
            return "5%~15%"
        else:
            return ">15%"

    async def _calc_has_losing_holdings(self, customer_id: int) -> bool:
        """检查客户是否有浮亏超过 5% 的持仓（用于 CAL-01 恐慌赎回检测）"""
        stmt = select(
            func.count(FinHoldings.id)
        ).where(
            FinHoldings.customer_id == customer_id,
            FinHoldings.status == "持有中",
            FinHoldings.profit_ratio < -0.05,
        )
        result = await self.db.execute(stmt)
        count = result.scalar() or 0
        return count > 0

    async def _calc_has_recent_redeems(self, customer_id: int) -> bool:
        """检查客户近 30 天内是否有赎回记录"""
        from datetime import timedelta
        thirty_days_ago = datetime.now() - timedelta(days=30)
        stmt = select(
            func.count(FinTransaction.id)
        ).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time >= thirty_days_ago,
            FinTransaction.transaction_type.in_(["redeem", "赎回"]),
        )
        result = await self.db.execute(stmt)
        count = result.scalar() or 0
        return count > 0

    @staticmethod
    def _parse_questionnaire_answers(answers) -> list:
        """统一解析风评问卷答案，兼容数据库中的多种 JSON 格式

        格式1: {"details": [{"q": 4, "a": "C"}, ...]}    ← risk_service 写入
        格式2: [{"q": 4, "a": "C"}, {"q": 1, "a": "B"}]  ← 前端/外部直接写入
        格式3: {"source": "demo"}                          ← 种子数据写入
        格式4: [10, 5, 7, 20, ...]                         ← api/operations 写入

        Returns:
            list[dict]: 统一的 [{"q": int, "a": str}, ...] 列表，无法解析时返回空列表
        """
        if answers is None:
            return []
        # 格式1/3: JSON 对象 → 取 details/items 字段
        if isinstance(answers, dict):
            items = answers.get("details") or answers.get("items") or []
            if isinstance(items, list):
                return items
            return []
        # 格式2/4: JSON 数组
        if isinstance(answers, list):
            if not answers:
                return []
            # 格式2: [{"q": 1, "a": "A"}, ...]
            if isinstance(answers[0], dict):
                return answers
            # 格式4: [10, 5, 7, ...] 整数数组，无法还原题号
            return []
        return []

    async def _calc_loss_tolerance(self, risk_assessment) -> str:
        """从风评问卷答案中提取亏损承受能力"""
        if not risk_assessment or not risk_assessment.answers:
            return "10%-20%"  # 默认基准
        details = self._parse_questionnaire_answers(risk_assessment.answers)
        # 查找第4题（亏损承受）的答案
        for d in details:
            if d.get("q") == 4:
                answer = d.get("a", "")
                if "不能" in answer:
                    return "不能承受任何亏损"
                elif "5%" in answer:
                    return "5%以内"
                elif "20%" in answer and "以上" in answer:  # 更具体的条件先检查
                    return "20%-40%"
                elif "40%" in answer:
                    return "40%以上"
                elif "10%" in answer or "20%" in answer:
                    return "10%-20%"
        # 未找到第4题答案，使用总分的保守推断
        total = risk_assessment.total_score or 50
        if total <= 30:
            return "不能承受任何亏损"
        elif total <= 45:
            return "5%以内"
        elif total <= 65:
            return "10%-20%"
        elif total <= 80:
            return "20%-40%"
        return "40%以上"

    # ── 双轨校准 → 行为数据采集辅助方法 ──────────────────────

    async def _calc_losing_holdings_detail(self, customer_id: int) -> list:
        """获取浮亏超过5%的持仓明细（用于CAL-01证据）"""
        stmt = select(
            FinHoldings.id, FinHoldings.profit_ratio, FinHoldings.current_value,
            FinHoldings.cost_amount, FinHoldings.profit_loss, FinProduct.product_name,
        ).join(FinProduct, FinHoldings.product_id == FinProduct.id).where(
            FinHoldings.customer_id == customer_id,
            FinHoldings.status == "持有中",
            FinHoldings.profit_ratio < -0.05,
        ).limit(5)
        result = await self.db.execute(stmt)
        rows = result.all()
        return [
            {
                "holding_id": row[0],
                "profit_ratio": float(row[1]) if row[1] is not None else 0,
                "current_value": float(row[2]) if row[2] is not None else 0,
                "cost_amount": float(row[3]) if row[3] is not None else 0,
                "profit_loss": float(row[4]) if row[4] is not None else 0,
                "product_name": row[5] or "未知产品",
            }
            for row in rows
        ]

    async def _calc_recent_redeems_detail(self, customer_id: int) -> list:
        """获取近30天赎回明细（用于CAL-01证据）"""
        from datetime import timedelta
        thirty_days_ago = datetime.now() - timedelta(days=30)
        stmt = select(
            FinTransaction.id, FinTransaction.amount, FinTransaction.create_time,
            FinTransaction.transaction_type, FinProduct.product_name,
        ).join(FinProduct, FinTransaction.product_id == FinProduct.id).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time >= thirty_days_ago,
            FinTransaction.transaction_type.in_(["redeem", "赎回"]),
        ).order_by(FinTransaction.create_time.desc()).limit(5)
        result = await self.db.execute(stmt)
        rows = result.all()
        return [
            {
                "transaction_id": f"T{row[0]}",
                "amount": float(row[1]) if row[1] is not None else 0,
                "date": str(row[2].date()) if row[2] else "",
                "transaction_type": row[3] or "赎回",
                "product_name": row[4] or "未知产品",
            }
            for row in rows
        ]

    async def _calc_max_losing_pct(self, customer_id: int) -> float:
        """获取持仓中最大浮亏比例"""
        from sqlalchemy import func as sql_func
        stmt = select(sql_func.min(FinHoldings.profit_ratio)).where(
            FinHoldings.customer_id == customer_id,
            FinHoldings.status == "持有中",
        )
        result = await self.db.execute(stmt)
        val = result.scalar()
        return float(val) if val is not None else 0.0

    async def _calc_strategy_changes_90d(self, customer_id: int) -> int:
        """统计近90天内调仓次数（买入/卖出/转换 操作次数作为策略变更代理）"""
        from datetime import timedelta
        ninety_days_ago = datetime.now() - timedelta(days=90)
        stmt = select(func.count(FinTransaction.id)).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time >= ninety_days_ago,
            FinTransaction.transaction_type.in_([
                "purchase", "redeem", "transfer",
                "申购", "赎回", "转换",
            ]),
        )
        result = await self.db.execute(stmt)
        count = result.scalar() or 0
        # 每次买入+卖出算一次策略调整 → 除以2取近似
        return int(count)

    async def _calc_strategy_change_dates(self, customer_id: int) -> list:
        """获取近90天内策略变更日期列表"""
        from datetime import timedelta
        ninety_days_ago = datetime.now() - timedelta(days=90)
        stmt = select(
            func.date(FinTransaction.create_time).label("trade_date"),
        ).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time >= ninety_days_ago,
            FinTransaction.transaction_type.in_([
                "purchase", "redeem", "transfer",
                "申购", "赎回", "转换",
            ]),
        ).distinct().order_by(func.date(FinTransaction.create_time).desc()).limit(10)
        result = await self.db.execute(stmt)
        return [str(row[0]) for row in result.all()]

    async def _calc_allocation_changes(self, customer_id: int) -> list:
        """获取近90天内资产配置变更记录"""
        # 简化实现：从持仓变更推断配置变化
        from datetime import timedelta
        ninety_days_ago = datetime.now() - timedelta(days=90)
        stmt = select(
            FinTransaction.id, FinTransaction.transaction_type, FinTransaction.amount,
            FinTransaction.create_time, FinProduct.product_type,
        ).join(FinProduct, FinTransaction.product_id == FinProduct.id).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time >= ninety_days_ago,
            FinTransaction.transaction_type.in_([
                "purchase", "redeem", "transfer",
                "申购", "赎回", "转换",
            ]),
        ).order_by(FinTransaction.create_time.desc()).limit(10)
        result = await self.db.execute(stmt)
        return [
            {
                "transaction_id": f"T{row[0]}",
                "type": row[1],
                "amount": float(row[2]) if row[2] is not None else 0,
                "date": str(row[3].date()) if row[3] else "",
                "product_type": row[4] or "未知",
            }
            for row in result.all()
        ]

    async def _calc_emotional_patterns(self, customer_id: int) -> list:
        """检测情绪化交易模式（追涨杀跌/FOMO等）"""
        patterns = []
        # 从维度三的 emotional_triggers 已经包含了追涨杀跌和FOMO标记
        # 这里基于交易数据做独立检测，与维度三互补
        from datetime import timedelta
        ninety_days_ago = datetime.now() - timedelta(days=90)

        # 检测近90天是否有频繁的买入后短期卖出（追涨杀跌模式）
        stmt = select(func.count(FinTransaction.id)).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time >= ninety_days_ago,
            FinTransaction.transaction_type.in_(["redeem", "赎回"]),
        )
        result = await self.db.execute(stmt)
        redeem_count = result.scalar() or 0

        stmt2 = select(func.count(FinTransaction.id)).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time >= ninety_days_ago,
            FinTransaction.transaction_type.in_(["purchase", "申购"]),
        )
        result2 = await self.db.execute(stmt2)
        purchase_count = result2.scalar() or 0

        # 频繁买卖（买入和卖出都超过3次）→ 潜在的追涨杀跌
        if redeem_count >= 3 and purchase_count >= 3:
            patterns.append("buy_at_peak")
            patterns.append("sell_at_trough")

        # 单笔买入超过月均交易额3倍 → FOMO
        stmt3 = select(func.avg(FinTransaction.amount)).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time >= ninety_days_ago,
            FinTransaction.transaction_type.in_(["purchase", "申购"]),
        )
        result3 = await self.db.execute(stmt3)
        avg_amount = result3.scalar()
        if avg_amount and float(avg_amount) > 0:
            stmt4 = select(func.max(FinTransaction.amount)).where(
                FinTransaction.customer_id == customer_id,
                FinTransaction.create_time >= ninety_days_ago,
                FinTransaction.transaction_type.in_(["purchase", "申购"]),
            )
            result4 = await self.db.execute(stmt4)
            max_amount = result4.scalar()
            if max_amount and float(max_amount) > float(avg_amount) * 3:
                patterns.append("fomo_large_buy")

        # 去重
        return list(set(patterns))

    async def _calc_trade_count_365d(self, customer_id: int) -> int:
        """近365天总交易笔数"""
        from datetime import timedelta
        one_year_ago = datetime.now() - timedelta(days=365)
        stmt = select(func.count(FinTransaction.id)).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time >= one_year_ago,
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    @staticmethod
    async def _calc_self_stated_frequency(risk_assessment) -> Optional[str]:
        """从风评问卷中提取客户自述的交易频率"""
        if not risk_assessment or not risk_assessment.answers:
            return None
        details = ProfileService._parse_questionnaire_answers(risk_assessment.answers)
        for d in details:
            if d.get("q") == 5:  # 假设第5题是关于交易频率
                answer = d.get("a", "")
                if "极低" in answer or "几乎不" in answer:
                    return "极低频"
                elif "低" in answer:
                    return "低频"
                elif "中" in answer or "一般" in answer:
                    return "中频"
                elif "高" in answer or "频繁" in answer:
                    return "高频"
        return None

    async def _calc_expired_risky_trades(
        self, customer_id: int, risk_assessment
    ) -> list:
        """查询风评过期后仍进行的R3+交易"""
        if not risk_assessment or not risk_assessment.valid_until:
            return []
        expiry_date = risk_assessment.valid_until
        if isinstance(expiry_date, date):
            from datetime import date as date_type
        else:
            return []

        # 查询过期后的交易
        stmt = select(
            FinTransaction.id, FinTransaction.amount, FinTransaction.create_time,
            FinProduct.risk_level, FinProduct.product_name,
        ).join(FinProduct, FinTransaction.product_id == FinProduct.id).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time > expiry_date,
            FinProduct.risk_level.in_(["R3", "R4", "R5"]),
            FinTransaction.transaction_type.in_(["purchase", "申购"]),
        ).order_by(FinTransaction.create_time.desc()).limit(5)
        result = await self.db.execute(stmt)
        return [
            {
                "transaction_id": f"T{row[0]}",
                "amount": float(row[1]) if row[1] is not None else 0,
                "date": str(row[2].date()) if row[2] else "",
                "product_level": row[3] or "R3",
                "product_name": row[4] or "未知产品",
            }
            for row in result.all()
        ]

    async def _calc_holding_product_summary(self, customer_id: int) -> list:
        """获取持仓产品摘要（用于CAL-06证据）"""
        stmt = select(
            FinProduct.product_name, FinProduct.risk_level, FinProduct.product_type,
            FinHoldings.current_value,
        ).join(FinProduct, FinHoldings.product_id == FinProduct.id).where(
            FinHoldings.customer_id == customer_id,
            FinHoldings.status == "持有中",
        ).limit(5)
        result = await self.db.execute(stmt)
        return [
            {
                "product_name": row[0] or "未知",
                "risk_level": row[1] or "N/A",
                "product_type": row[2] or "N/A",
                "current_value": float(row[3]) if row[3] is not None else 0,
            }
            for row in result.all()
        ]

    # ── FM-03/FM-04/FM-05 熔断数据采集辅助方法 ──────────────────

    async def _calc_abnormal_behaviors(self, customer_id: int) -> list:
        """从交易流水检测异常行为（维度四 + FM-05 熔断依赖）"""
        from datetime import timedelta
        now = datetime.now()
        thirty_days_ago = now - timedelta(days=30)
        behaviors = []

        # B001: 30天内赎回次数≥5 → 频繁赎回
        redeem_stmt = select(func.count(FinTransaction.id)).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time >= thirty_days_ago,
            FinTransaction.transaction_type.in_(["redeem", "赎回"]),
        )
        redeem_count = (await self.db.execute(redeem_stmt)).scalar() or 0
        if redeem_count >= 5:
            behaviors.append({"id": "B001", "name": "频繁赎回", "risk": "中"})

        # B002: 单日交易金额超过账户总资产50%
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        daily_amt_stmt = select(func.sum(FinTransaction.amount)).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time >= today_start,
        )
        daily_total = (await self.db.execute(daily_amt_stmt)).scalar() or 0
        total_assets = await self._get_total_assets(customer_id)
        if total_assets > 0 and float(daily_total) > total_assets * 0.5:
            behaviors.append({"id": "B002", "name": "大额集中交易", "risk": "中"})

        # B003: 非正常时段交易（凌晨0:00-6:00）
        night_stmt = select(func.count(FinTransaction.id)).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time >= thirty_days_ago,
            func.hour(FinTransaction.create_time).between(0, 5),
        )
        night_count = (await self.db.execute(night_stmt)).scalar() or 0
        if night_count >= 3:
            behaviors.append({"id": "B003", "name": "非正常时段交易", "risk": "低"})

        # B006: 产品风险越级（在 purchase API 中已有校验，此处标记）
        expired_stmt = select(func.count(FinTransaction.id)).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time >= thirty_days_ago,
            FinTransaction.transaction_type.in_(["purchase", "申购"]),
        )
        expired_trades = (await self.db.execute(expired_stmt)).scalar() or 0
        # 检测风评过期后的交易
        ra_stmt = select(RiskAssessment).where(
            RiskAssessment.customer_id == customer_id
        ).order_by(RiskAssessment.create_time.desc()).limit(1)
        ra_result = await self.db.execute(ra_stmt)
        risk_assessment = ra_result.scalar_one_or_none()
        if risk_assessment and risk_assessment.valid_until:
            if isinstance(risk_assessment.valid_until, date):
                expiry = datetime.combine(risk_assessment.valid_until, datetime.min.time())
                if now > expiry:
                    post_expiry_stmt = select(func.count(FinTransaction.id)).where(
                        FinTransaction.customer_id == customer_id,
                        FinTransaction.create_time > expiry,
                        FinTransaction.transaction_type.in_(["purchase", "申购"]),
                    )
                    post_expiry_count = (await self.db.execute(post_expiry_stmt)).scalar() or 0
                    if post_expiry_count > 0:
                        behaviors.append({"id": "B006", "name": "风评过期后交易", "risk": "高"})

        return behaviors

    async def _get_total_assets(self, customer_id: int) -> float:
        """获取客户总资产"""
        profile_stmt = select(FinCustomerProfile).where(FinCustomerProfile.customer_id == customer_id)
        result = await self.db.execute(profile_stmt)
        profile = result.scalar_one_or_none()
        if profile and profile.total_assets:
            return float(profile.total_assets)
        return 0.0

    async def _calc_is_dishonest(self, customer_id: int) -> bool:
        """检查客户是否为失信被执行人（从画像标记/风控记录查询）"""
        try:
            profile_stmt = select(FinCustomerProfile).where(FinCustomerProfile.customer_id == customer_id)
            result = await self.db.execute(profile_stmt)
            profile = result.scalar_one_or_none()
            if profile and profile.risk_flag == "dishonest":
                return True
            # 从风控预警记录查询是否有失信标记
            alert_stmt = select(func.count(FinRiskAlert.id)).where(
                FinRiskAlert.customer_id == customer_id,
                FinRiskAlert.alert_type == "dishonest",
            )
            alert_count = (await self.db.execute(alert_stmt)).scalar() or 0
            return alert_count > 0
        except Exception:
            return False

    @staticmethod
    def _calc_is_foreign(user) -> bool:
        """判断是否为外籍人士（从身份证号/国籍字段推断）"""
        if not user or not user.id_card:
            return False
        # 中国身份证为18位数字(末位可为X)，非此格式视为外籍证件
        import re
        id_card = str(user.id_card).strip().upper()
        return not bool(re.match(r'^\d{17}[\dX]$', id_card))

    @staticmethod
    def _calc_id_expired_days(user) -> int:
        """计算身份证过期天数"""
        if not user or not user.id_card_expiry:
            return 0
        expiry = user.id_card_expiry
        if isinstance(expiry, date):
            delta = (date.today() - expiry).days
            return max(0, delta)
        return 0

    @staticmethod
    def _calc_identity_check_failed(user) -> bool:
        """检查联网核查是否通过（从用户状态推断）"""
        if not user:
            return False
        # status 字段包含身份核查状态
        return user.status in ("身份待核查", "核查未通过", "identity_unverified")

    @staticmethod
    async def _calc_on_sanction_list(customer_id: int, profile) -> bool:
        """检查客户是否在制裁名单中"""
        if profile and profile.risk_flag == "sanctioned":
            return True
        # 从风控预警记录查询是否有制裁标记
        return False  # 默认无制裁，实际应接外部API

    async def _calc_daily_loss_pct(self, customer_id: int, profile) -> float:
        """计算单日亏损占总资产比例（FM-05 熔断依赖）"""
        total_assets = float(profile.total_assets) if profile and profile.total_assets else 0
        if total_assets <= 0:
            return 0.0

        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        # 从持仓盈亏变动统计当日亏损（简化：取当日所有亏钱交易之和）
        loss_stmt = select(func.sum(FinTransaction.amount)).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time >= today_start,
            FinTransaction.transaction_type.in_(["redeem", "赎回"]),
        )
        daily_redeem = (await self.db.execute(loss_stmt)).scalar() or 0
        # 持仓浮动亏损
        holdings_loss_stmt = select(func.sum(FinHoldings.profit_loss)).where(
            FinHoldings.customer_id == customer_id,
            FinHoldings.status == "持有中",
            FinHoldings.profit_loss < 0,
        )
        holdings_loss = (await self.db.execute(holdings_loss_stmt)).scalar() or 0

        total_loss = float(daily_redeem) + abs(float(holdings_loss))
        return round(total_loss / total_assets, 4) if total_assets > 0 else 0.0

    async def _calc_consecutive_redeem_pct(self, customer_id: int, profile) -> float:
        """计算连续3日赎回占总资产比例（FM-05 熔断依赖）"""
        total_assets = float(profile.total_assets) if profile and profile.total_assets else 0
        if total_assets <= 0:
            return 0.0

        from datetime import timedelta
        three_days_ago = datetime.now() - timedelta(days=3)
        redeem_stmt = select(func.sum(FinTransaction.amount)).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time >= three_days_ago,
            FinTransaction.transaction_type.in_(["redeem", "赎回"]),
        )
        total_redeem = (await self.db.execute(redeem_stmt)).scalar() or 0
        return round(float(total_redeem) / total_assets, 4)

    async def _calc_account_theft_suspected(self, customer_id: int) -> bool:
        """检测账户是否疑似被盗用（FM-05 熔断依赖）"""
        from datetime import timedelta
        thirty_days_ago = datetime.now() - timedelta(days=30)

        # 综合判断：非正常时段交易 + 大额交易 + 地址变更
        night_stmt = select(func.count(FinTransaction.id)).where(
            FinTransaction.customer_id == customer_id,
            FinTransaction.create_time >= thirty_days_ago,
            func.hour(FinTransaction.create_time).between(0, 5),
        )
        night_count = (await self.db.execute(night_stmt)).scalar() or 0

        # 信息频繁变更检测（B007）
        # 简化：检查是否有手机/地址变更记录
        # 实际应查询变更日志表
        if night_count >= 5:
            return True

        return False

    # ── 持久化辅助方法 ──────────────────────────────────────────

    async def _persist_calibration(
        self, customer_id: int, calibration_info: CalibrationInfo, trigger_type: str
    ):
        """持久化校准记录到专用表 + 更新画像快照"""
        from app.model.entities import FinCalibrationRecord

        # 写入校准历史表
        record = FinCalibrationRecord(
            customer_id=customer_id,
            calibrate_time=calibration_info.calibrate_time or datetime.now(),
            direction=calibration_info.direction,
            self_reported=calibration_info.self_reported,
            behavioral=calibration_info.behavioral,
            triggered_rules=[
                {
                    "rule_id": r.rule_id if hasattr(r, 'rule_id') else r.get("rule_id", ""),
                    "rule_name": r.rule_name if hasattr(r, 'rule_name') else r.get("rule_name", ""),
                    "direction": r.direction if hasattr(r, 'direction') else r.get("direction", ""),
                    "detail": r.detail if hasattr(r, 'detail') else r.get("detail", ""),
                    "evidence": r.evidence if hasattr(r, 'evidence') else r.get("evidence", {}),
                }
                for r in calibration_info.triggered_rules
            ],
            summary=calibration_info.summary,
            trigger_type=trigger_type,
        )
        self.db.add(record)

        # 同步更新画像主表的校准快照
        stmt = select(FinCustomerProfile).where(FinCustomerProfile.customer_id == customer_id)
        result = await self.db.execute(stmt)
        profile = result.scalar_one_or_none()
        if profile:
            profile.calibration_json = {
                "calibrate_time": calibration_info.calibrate_time.isoformat() if calibration_info.calibrate_time else None,
                "direction": calibration_info.direction,
                "self_reported": calibration_info.self_reported,
                "behavioral": calibration_info.behavioral,
                "triggered_rules": [
                    r.model_dump() if hasattr(r, 'model_dump') else r
                    for r in calibration_info.triggered_rules
                ],
                "summary": calibration_info.summary,
            }

        await self.db.flush()

    async def _update_profile_after_assess(
        self, customer_id: int, risk_level: str, risk_score: int, dimension_scores: dict
    ):
        """研判后更新画像表（含完整画像 JSON）"""
        stmt = select(FinCustomerProfile).where(FinCustomerProfile.customer_id == customer_id)
        result = await self.db.execute(stmt)
        profile = result.scalar_one_or_none()

        # 序列化完整画像 JSON
        profile_json = {
            "customer_id": customer_id,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "dimensions": {
                k: {
                    "score": v["score"],
                    "detail": v.get("detail", {}) if isinstance(v.get("detail"), dict) else v.get("detail"),
                }
                for k, v in dimension_scores.items()
            },
            "updated_at": datetime.now().isoformat(),
        }

        if profile:
            profile.risk_level = risk_level
            profile.risk_score = risk_score
            profile.basic_score = dimension_scores["basic"]["score"]
            profile.experience_score = dimension_scores["experience"]["score"]
            profile.risk_pref_score = dimension_scores["risk_pref"]["score"]
            profile.behavior_score = dimension_scores["behavior"]["score"]
            profile.profile_json = profile_json
            profile.update_time = datetime.now()
        else:
            profile = FinCustomerProfile(
                customer_id=customer_id,
                risk_level=risk_level,
                risk_score=risk_score,
                basic_score=dimension_scores["basic"]["score"],
                experience_score=dimension_scores["experience"]["score"],
                risk_pref_score=dimension_scores["risk_pref"]["score"],
                behavior_score=dimension_scores["behavior"]["score"],
                profile_json=profile_json,
            )
            self.db.add(profile)

        await self.db.flush()
        await self.cache.invalidate(customer_id)

    def _profile_to_dict(self, profile: FinCustomerProfile) -> dict:
        return {
            "_schema_version": PROFILE_CACHE_SCHEMA_VERSION,
            "id": getattr(profile, "id", None),
            "customer_id": getattr(profile, "customer_id", None),
            "risk_level": getattr(profile, "risk_level", None),
            "risk_score": getattr(profile, "risk_score", None),
            "investment_experience": getattr(profile, "investment_experience", None),
            "annual_income_range": getattr(profile, "annual_income_range", None),
            "total_assets": str(profile.total_assets) if getattr(profile, "total_assets", None) else None,
            "asset_allocation": getattr(profile, "asset_allocation", None),
            "product_preference": getattr(profile, "product_preference", None),
            "confidence_score": (
                str(profile.confidence_score) if getattr(profile, "confidence_score", None) else None
            ),
            "basic_score": str(profile.basic_score) if getattr(profile, "basic_score", None) else None,
            "experience_score": (
                str(profile.experience_score) if getattr(profile, "experience_score", None) else None
            ),
            "risk_pref_score": (
                str(profile.risk_pref_score) if getattr(profile, "risk_pref_score", None) else None
            ),
            "behavior_score": (
                str(profile.behavior_score) if getattr(profile, "behavior_score", None) else None
            ),
            "risk_flag": getattr(profile, "risk_flag", None),
            "profile_json": getattr(profile, "profile_json", None),
            "create_time": getattr(profile, "create_time", None),
            "update_time": getattr(profile, "update_time", None),
        }

    @staticmethod
    def _map_asset_to_range(assets) -> str:
        if assets is None:
            return None
        a = float(assets)
        if a < 50000:
            return "<5万"
        elif a < 200000:
            return "5-20万"
        elif a < 500000:
            return "20-50万"
        elif a < 1000000:
            return "50-100万"
        elif a < 5000000:
            return "100-500万"
        elif a < 10000000:
            return "500-1000万"
        return ">1000万"
