"""
画像业务编排服务
画像创建 / 查询（Cache-Aside） / 增量更新 / 完整研判
"""

from typing import Optional, List
from datetime import datetime, date
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.entities import FinCustomerProfile, CustomerTag, SysUser, RiskAssessment
from app.model.schemas import ProfileResult, DimensionScore, DimensionDetail
from app.engine.dimension_calculator import DimensionCalculator
from app.engine.circuit_breaker import CircuitBreaker
from app.engine.special_case import SpecialCaseHandler
from app.engine.confidence import ConfidenceCalculator
from app.engine.score_mapper import (
    map_score_to_risk_level, calc_total_score, get_suitable_products,
)
from app.memory.profile_cache import ProfileCache
from app.memory.long_term import LongTermMemory
from app.utils.exceptions import ProfileNotFound, CircuitBreakerTriggered


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
        if cached:
            return cached

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
            confidence_score=0.85,  # 默认，后续可扩展
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
                    if winning is tag:
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
        """收集客户全量数据"""
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
            # 以下字段可从其他表获取（简化处理用默认值）
            "max_product_type": "混合基金/指数基金(R3)",
            "trade_frequency": "低频",
            "historical_return": "5%~15%",
            "loss_tolerance": "10%-20%",
            "abnormal_behaviors": [],
            "is_student": False,
            "is_dishonest": False,
            "is_foreign": False,
            "id_expired_days": 0,
            "identity_check_failed": False,
            "on_sanction_list": False,
            "daily_loss_pct": 0,
            "consecutive_redeem_pct": 0,
            "account_theft_suspected": False,
            "self_assessment_level": None,
        }

    async def _update_profile_after_assess(
        self, customer_id: int, risk_level: str, risk_score: int, dimension_scores: dict
    ):
        """研判后更新画像表"""
        stmt = select(FinCustomerProfile).where(FinCustomerProfile.customer_id == customer_id)
        result = await self.db.execute(stmt)
        profile = result.scalar_one_or_none()

        if profile:
            profile.risk_level = risk_level
            profile.risk_score = risk_score
            profile.basic_score = dimension_scores["basic"]["score"]
            profile.experience_score = dimension_scores["experience"]["score"]
            profile.risk_pref_score = dimension_scores["risk_pref"]["score"]
            profile.behavior_score = dimension_scores["behavior"]["score"]
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
            )
            self.db.add(profile)

        await self.db.flush()
        await self.cache.invalidate(customer_id)

    def _profile_to_dict(self, profile: FinCustomerProfile) -> dict:
        return {
            "customer_id": profile.customer_id,
            "risk_level": profile.risk_level,
            "risk_score": profile.risk_score,
            "total_assets": str(profile.total_assets) if profile.total_assets else None,
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
