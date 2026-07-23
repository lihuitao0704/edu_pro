"""
RuleLoader — 规则加载服务
封装"MySQL risk_rule 表 → Python 硬编码 fallback"逻辑

- RULE_LOADER_USE_DB=false（默认）: 直接从 rules_config.py import
- RULE_LOADER_USE_DB=true: 从 risk_rule 表读取，读不到时 fallback

用法:
    loader = RuleLoader(db_session)
    age_rules = await loader.get_scoring_rule("D1-AGE")  # → {"18-25": 8, ...}
    cb_rules  = await loader.get_circuit_breaker_rules()  # → [FM-01, ...]
"""

from typing import Optional, List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.entities import RiskRule
from app.config import rules_config as _fallback


class RuleLoader:
    """规则加载器：优先 MySQL，fallback 到 Python 硬编码"""

    def __init__(self, db: Optional[AsyncSession] = None):
        from app.config.settings import get_settings
        self._db = db
        self._use_db = get_settings().rule_loader.use_db

    # ═══════════════════════════════════════════════════════════════
    # 通用查询
    # ═══════════════════════════════════════════════════════════════

    async def _get_rule_by_id(self, rule_id: str) -> Optional[dict]:
        """按 rule_id 查单条规则，返回 config_json 或 None"""
        if not (self._use_db and self._db):
            return None
        stmt = select(RiskRule.config_json).where(
            RiskRule.rule_id == rule_id,
            RiskRule.is_active == True,
        )
        result = await self._db.execute(stmt)
        row = result.one_or_none()
        return row[0] if row else None

    async def _get_rules_by_type(self, rule_type: str) -> List[dict]:
        """按 rule_type 查所有规则，返回 config_json 列表"""
        if not (self._use_db and self._db):
            return []
        stmt = select(RiskRule.config_json).where(
            RiskRule.rule_type == rule_type,
            RiskRule.is_active == True,
        )
        result = await self._db.execute(stmt)
        return [row[0] for row in result.fetchall()]

    async def _get_rules_by_dimension(self, dimension: str) -> List[dict]:
        """按 dimension 查所有规则"""
        if not (self._use_db and self._db):
            return []
        stmt = select(RiskRule.config_json).where(
            RiskRule.dimension == dimension,
            RiskRule.rule_type == "scoring",
            RiskRule.is_active == True,
        )
        result = await self._db.execute(stmt)
        return [row[0] for row in result.fetchall()]

    # ═══════════════════════════════════════════════════════════════
    # 维度一：基础属性特征
    # ═══════════════════════════════════════════════════════════════

    async def get_age_score(self) -> dict:
        return await self._get_rule_by_id("D1-AGE") or _fallback.AGE_SCORE

    async def get_education_score(self) -> dict:
        return await self._get_rule_by_id("D1-EDU") or _fallback.EDUCATION_SCORE

    async def get_occupation_score(self) -> dict:
        return await self._get_rule_by_id("D1-OCC") or _fallback.OCCUPATION_SCORE

    async def get_income_score(self) -> dict:
        return await self._get_rule_by_id("D1-INC") or _fallback.INCOME_SCORE

    async def get_asset_score(self) -> dict:
        return await self._get_rule_by_id("D1-AST") or _fallback.ASSET_SCORE

    # ═══════════════════════════════════════════════════════════════
    # 维度二：投资经验特征
    # ═══════════════════════════════════════════════════════════════

    async def get_investment_years_score(self) -> dict:
        return await self._get_rule_by_id("D2-YEARS") or _fallback.INVESTMENT_YEARS_SCORE

    async def get_product_complexity_score(self) -> dict:
        return await self._get_rule_by_id("D2-COMPLEX") or _fallback.PRODUCT_COMPLEXITY_SCORE

    async def get_trade_frequency_score(self) -> dict:
        return await self._get_rule_by_id("D2-FREQ") or _fallback.TRADE_FREQUENCY_SCORE

    async def get_historical_return_score(self) -> dict:
        return await self._get_rule_by_id("D2-RETURN") or _fallback.HISTORICAL_RETURN_SCORE

    # ═══════════════════════════════════════════════════════════════
    # 维度三：风险偏好特征
    # ═══════════════════════════════════════════════════════════════

    async def get_risk_assessment_mapping(self) -> dict:
        return await self._get_rule_by_id("D3-MAP") or _fallback.RISK_ASSESSMENT_MAPPING

    async def get_emotional_trading_penalty(self) -> list:
        return await self._get_rule_by_id("D3-EMOTION") or _fallback.EMOTIONAL_TRADING_PENALTY

    async def get_loss_tolerance_adjustment(self) -> dict:
        return await self._get_rule_by_id("D3-LOSS") or _fallback.LOSS_TOLERANCE_ADJUSTMENT

    # ═══════════════════════════════════════════════════════════════
    # 维度四：行为异常特征
    # ═══════════════════════════════════════════════════════════════

    async def get_behavior_abnormal_rules(self) -> list:
        return await self._get_rule_by_id("D4-BEHAVIOR") or _fallback.BEHAVIOR_ABNORMAL_RULES

    async def get_behavior_abnormal_score(self) -> dict:
        return await self._get_rule_by_id("D4-SCORE") or _fallback.BEHAVIOR_ABNORMAL_SCORE

    # ═══════════════════════════════════════════════════════════════
    # 通用映射
    # ═══════════════════════════════════════════════════════════════

    async def get_risk_level_mapping(self) -> list:
        return await self._get_rule_by_id("LEVEL-MAP") or _fallback.RISK_LEVEL_MAPPING

    async def get_suitability_matrix(self) -> dict:
        return await self._get_rule_by_id("SUIT-MATRIX") or _fallback.SUITABILITY_MATRIX

    async def get_dimension_weights(self) -> dict:
        return await self._get_rule_by_id("DIM-WEIGHT") or _fallback.DIMENSION_WEIGHTS

    async def get_confidence_source_initial(self) -> dict:
        return await self._get_rule_by_id("CONFIDENCE-SRC") or _fallback.CONFIDENCE_SOURCE_INITIAL

    async def get_recommendation_weights(self) -> dict:
        return await self._get_rule_by_id("RECOMMEND-WEIGHT") or _fallback.RECOMMENDATION_WEIGHTS

    async def get_asset_allocation_templates(self) -> dict:
        return await self._get_rule_by_id("ASSET-ALLOC") or _fallback.ASSET_ALLOCATION_TEMPLATES

    # ═══════════════════════════════════════════════════════════════
    # 熔断规则
    # ═══════════════════════════════════════════════════════════════

    async def get_circuit_breaker_rules(self) -> list:
        """返回全部熔断规则 FM-01 ~ FM-05"""
        db_rules = await self._get_rules_by_type("circuit_breaker")
        return db_rules if db_rules else _fallback.CIRCUIT_BREAKER_RULES

    # ═══════════════════════════════════════════════════════════════
    # 特殊场景规则
    # ═══════════════════════════════════════════════════════════════

    async def get_special_population_rules(self) -> dict:
        rules = {}
        for rid in ("SP-STUDENT", "SP-DISHONEST", "SP-FOREIGN"):
            row = await self._get_rule_by_id(rid)
            # 重建 key（去掉 "SP-" 前缀对应的中文名）
            if row:
                key = {
                    "SP-STUDENT": "在校学生", "SP-DISHONEST": "失信被执行人", "SP-FOREIGN": "外籍人士",
                }.get(rid, rid)
                rules[key] = row
        return rules if rules else _fallback.SPECIAL_POPULATION_RULES

    async def get_self_vs_ai_conflict(self) -> dict:
        return await self._get_rule_by_id("SP-CONFLICT") or _fallback.SELF_VS_AI_CONFLICT

    async def get_incomplete_info_rules(self) -> dict:
        return await self._get_rule_by_id("SP-INCOMPLETE") or _fallback.INCOMPLETE_INFO_RULES
