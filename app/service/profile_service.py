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
    FinHoldings, FinProduct, FinTransaction,
)
from app.model.schemas import ProfileResult, DimensionScore, DimensionDetail
from app.engine.dimension_calculator import DimensionCalculator
from app.engine.circuit_breaker import CircuitBreaker
from app.engine.special_case import SpecialCaseHandler
from app.engine.confidence import ConfidenceCalculator
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
            # TODO: 以下异常行为字段需从交易流水/风控数据动态获取，当前硬编码为安全值
            # FM-04（身份异常）和 FM-05（交易熔断）依赖这些字段
            "abnormal_behaviors": [],
            "is_student": user.occupation == "在校学生",
            "is_dishonest": False,         # TODO: 从失信被执行人名单查询
            "is_foreign": False,
            "id_expired_days": 0,          # TODO: 从身份证有效期计算
            "identity_check_failed": False,  # TODO: 从联网核查结果获取
            "on_sanction_list": False,      # TODO: 从制裁名单筛查
            "daily_loss_pct": 0,            # TODO: 从当日交易流水计算
            "consecutive_redeem_pct": 0,    # TODO: 从连续3日赎回记录计算
            "account_theft_suspected": False,  # TODO: 从异常交易检测获取
            "self_assessment_level": risk_assessment.risk_level if risk_assessment else None,
        }

    # ── 动态计算辅助方法 ──────────────────────────────────────

    async def _calc_max_product_type(self, customer_id: int) -> str:
        """从持仓产品中取最高风险等级的产品类型（用于维度二复杂度评分）"""
        stmt = (
            select(FinProduct)
            .join(FinHoldings, FinHoldings.product_id == FinProduct.id)
            .where(
                FinHoldings.customer_id == customer_id,
                FinHoldings.status == "持有",
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
            FinHoldings.status == "持有",
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

    @staticmethod
    def _calc_loss_tolerance(risk_assessment) -> str:
        """从风评问卷答案中提取亏损承受能力"""
        if not risk_assessment or not risk_assessment.answers:
            return "10%-20%"  # 默认基准
        answers = risk_assessment.answers
        details = answers.get("details", [])
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
            "id": profile.id,
            "customer_id": profile.customer_id,
            "risk_level": profile.risk_level,
            "risk_score": profile.risk_score,
            "investment_experience": profile.investment_experience,
            "annual_income_range": profile.annual_income_range,
            "total_assets": str(profile.total_assets) if profile.total_assets else None,
            "asset_allocation": profile.asset_allocation,
            "product_preference": profile.product_preference,
            "confidence_score": (
                str(profile.confidence_score) if profile.confidence_score else None
            ),
            "basic_score": str(profile.basic_score) if profile.basic_score else None,
            "experience_score": (
                str(profile.experience_score) if profile.experience_score else None
            ),
            "risk_pref_score": (
                str(profile.risk_pref_score) if profile.risk_pref_score else None
            ),
            "behavior_score": (
                str(profile.behavior_score) if profile.behavior_score else None
            ),
            "risk_flag": profile.risk_flag,
            "profile_json": profile.profile_json,
            "create_time": profile.create_time,
            "update_time": profile.update_time,
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
