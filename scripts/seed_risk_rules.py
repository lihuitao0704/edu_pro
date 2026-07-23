"""将 rules_config.py 中的规则导入 MySQL risk_rule 表（幂等：重复执行按 rule_id 更新）

用法: python scripts/seed_risk_rules.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.config.database import async_session_factory
from app.model.entities import RiskRule
from app.config.rules_config import (
    AGE_SCORE, EDUCATION_SCORE, OCCUPATION_SCORE, INCOME_SCORE, ASSET_SCORE,
    INVESTMENT_YEARS_SCORE, PRODUCT_COMPLEXITY_SCORE,
    TRADE_FREQUENCY_SCORE, HISTORICAL_RETURN_SCORE,
    RISK_ASSESSMENT_MAPPING, EMOTIONAL_TRADING_PENALTY, LOSS_TOLERANCE_ADJUSTMENT,
    BEHAVIOR_ABNORMAL_RULES, BEHAVIOR_ABNORMAL_SCORE,
    RISK_LEVEL_MAPPING, SUITABILITY_MATRIX,
    CIRCUIT_BREAKER_RULES,
    SPECIAL_POPULATION_RULES, SELF_VS_AI_CONFLICT, INCOMPLETE_INFO_RULES,
    DIMENSION_WEIGHTS, CONFIDENCE_SOURCE_INITIAL,
    RECOMMENDATION_WEIGHTS, ASSET_ALLOCATION_TEMPLATES,
)

RULES = [
    # ═══════════ 维度一：基础属性特征 ═══════════
    {"rule_id": "D1-AGE",      "rule_name": "年龄评分",       "rule_type": "scoring", "dimension": "basic",
     "config_json": AGE_SCORE, "weight": 0.20},
    {"rule_id": "D1-EDU",      "rule_name": "学历评分",       "rule_type": "scoring", "dimension": "basic",
     "config_json": EDUCATION_SCORE, "weight": 0.20},
    {"rule_id": "D1-OCC",      "rule_name": "职业评分",       "rule_type": "scoring", "dimension": "basic",
     "config_json": OCCUPATION_SCORE, "weight": 0.20},
    {"rule_id": "D1-INC",      "rule_name": "收入评分",       "rule_type": "scoring", "dimension": "basic",
     "config_json": INCOME_SCORE, "weight": 0.20},
    {"rule_id": "D1-AST",      "rule_name": "资产评分",       "rule_type": "scoring", "dimension": "basic",
     "config_json": ASSET_SCORE, "weight": 0.20},

    # ═══════════ 维度二：投资经验特征 ═══════════
    {"rule_id": "D2-YEARS",    "rule_name": "投资年限评分",   "rule_type": "scoring", "dimension": "experience",
     "config_json": INVESTMENT_YEARS_SCORE, "weight": 0.25},
    {"rule_id": "D2-COMPLEX",  "rule_name": "产品复杂度评分", "rule_type": "scoring", "dimension": "experience",
     "config_json": PRODUCT_COMPLEXITY_SCORE, "weight": 0.25},
    {"rule_id": "D2-FREQ",     "rule_name": "交易频率评分",   "rule_type": "scoring", "dimension": "experience",
     "config_json": TRADE_FREQUENCY_SCORE, "weight": 0.25},
    {"rule_id": "D2-RETURN",   "rule_name": "历史收益评分",   "rule_type": "scoring", "dimension": "experience",
     "config_json": HISTORICAL_RETURN_SCORE, "weight": 0.25},

    # ═══════════ 维度三：风险偏好特征 ═══════════
    {"rule_id": "D3-MAP",      "rule_name": "风评等级映射",   "rule_type": "scoring", "dimension": "risk_pref",
     "config_json": RISK_ASSESSMENT_MAPPING, "weight": 0.333},
    {"rule_id": "D3-EMOTION",  "rule_name": "情绪化交易扣分", "rule_type": "scoring", "dimension": "risk_pref",
     "config_json": EMOTIONAL_TRADING_PENALTY, "weight": 0.333},
    {"rule_id": "D3-LOSS",     "rule_name": "亏损承受调整",   "rule_type": "scoring", "dimension": "risk_pref",
     "config_json": LOSS_TOLERANCE_ADJUSTMENT, "weight": 0.333},

    # ═══════════ 维度四：行为异常特征 ═══════════
    {"rule_id": "D4-BEHAVIOR", "rule_name": "异常行为规则",   "rule_type": "scoring", "dimension": "behavior",
     "config_json": BEHAVIOR_ABNORMAL_RULES, "weight": 0.50},
    {"rule_id": "D4-SCORE",    "rule_name": "异常行为得分",   "rule_type": "scoring", "dimension": "behavior",
     "config_json": BEHAVIOR_ABNORMAL_SCORE, "weight": 0.50},

    # ═══════════ 通用映射规则 ═══════════
    {"rule_id": "LEVEL-MAP",   "rule_name": "等级映射",       "rule_type": "scoring", "dimension": None,
     "config_json": RISK_LEVEL_MAPPING, "weight": None},
    {"rule_id": "SUIT-MATRIX", "rule_name": "适当性矩阵",     "rule_type": "scoring", "dimension": None,
     "config_json": SUITABILITY_MATRIX, "weight": None},

    # ═══════════ 权重配置 ═══════════
    {"rule_id": "DIM-WEIGHT",  "rule_name": "维度权重",       "rule_type": "scoring", "dimension": None,
     "config_json": DIMENSION_WEIGHTS, "weight": None},
    {"rule_id": "CONFIDENCE-SRC", "rule_name": "置信度初始权重", "rule_type": "scoring", "dimension": None,
     "config_json": CONFIDENCE_SOURCE_INITIAL, "weight": None},
    {"rule_id": "RECOMMEND-WEIGHT", "rule_name": "推荐引擎权重", "rule_type": "scoring", "dimension": None,
     "config_json": RECOMMENDATION_WEIGHTS, "weight": None},
    {"rule_id": "ASSET-ALLOC", "rule_name": "资产配置模板",   "rule_type": "scoring", "dimension": None,
     "config_json": ASSET_ALLOCATION_TEMPLATES, "weight": None},

    # ═══════════ 熔断规则 FM-01 ~ FM-05 ═══════════
    {"rule_id": "FM-01",       "rule_name": "年龄限制",       "rule_type": "circuit_breaker", "dimension": None,
     "config_json": CIRCUIT_BREAKER_RULES[0], "weight": None},
    {"rule_id": "FM-02",       "rule_name": "收入与资产限制", "rule_type": "circuit_breaker", "dimension": None,
     "config_json": CIRCUIT_BREAKER_RULES[1], "weight": None},
    {"rule_id": "FM-03",       "rule_name": "风评时效检查",   "rule_type": "circuit_breaker", "dimension": None,
     "config_json": CIRCUIT_BREAKER_RULES[2], "weight": None},
    {"rule_id": "FM-04",       "rule_name": "身份异常检查",   "rule_type": "circuit_breaker", "dimension": None,
     "config_json": CIRCUIT_BREAKER_RULES[3], "weight": None},
    {"rule_id": "FM-05",       "rule_name": "异常交易熔断",   "rule_type": "circuit_breaker", "dimension": None,
     "config_json": CIRCUIT_BREAKER_RULES[4], "weight": None},

    # ═══════════ 特殊场景规则 ═══════════
    {"rule_id": "SP-STUDENT",  "rule_name": "在校学生",       "rule_type": "special", "dimension": None,
     "config_json": SPECIAL_POPULATION_RULES.get("在校学生", {}), "weight": None},
    {"rule_id": "SP-DISHONEST","rule_name": "失信被执行人",   "rule_type": "special", "dimension": None,
     "config_json": SPECIAL_POPULATION_RULES.get("失信被执行人", {}), "weight": None},
    {"rule_id": "SP-FOREIGN",  "rule_name": "外籍人士",       "rule_type": "special", "dimension": None,
     "config_json": SPECIAL_POPULATION_RULES.get("外籍人士", {}), "weight": None},
    {"rule_id": "SP-CONFLICT", "rule_name": "自评vs AI冲突",  "rule_type": "special", "dimension": None,
     "config_json": SELF_VS_AI_CONFLICT, "weight": None},
    {"rule_id": "SP-INCOMPLETE","rule_name": "信息不完整规则", "rule_type": "special", "dimension": None,
     "config_json": INCOMPLETE_INFO_RULES, "weight": None},
]


async def seed():
    async with async_session_factory() as session:
        inserted = 0
        updated = 0
        for item in RULES:
            # 检查是否已存在
            stmt = select(RiskRule).where(RiskRule.rule_id == item["rule_id"])
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                existing.rule_name   = item["rule_name"]
                existing.rule_type   = item["rule_type"]
                existing.dimension   = item.get("dimension")
                existing.config_json = item["config_json"]
                existing.weight      = item.get("weight")
                existing.version     = "1.0"
                existing.is_active   = True
                updated += 1
                print(f"  [UPDATE] {item['rule_id']} - {item['rule_name']}")
            else:
                rule = RiskRule(
                    rule_id     = item["rule_id"],
                    rule_name   = item["rule_name"],
                    rule_type   = item["rule_type"],
                    dimension   = item.get("dimension"),
                    config_json = item["config_json"],
                    weight      = item.get("weight"),
                    version     = "1.0",
                    is_active   = True,
                )
                session.add(rule)
                inserted += 1
                print(f"  [INSERT] {item['rule_id']} - {item['rule_name']}")

        await session.commit()
        print(f"\n完成: 新增 {inserted} 条，更新 {updated} 条，共 {len(RULES)} 条规则")


if __name__ == "__main__":
    asyncio.run(seed())
