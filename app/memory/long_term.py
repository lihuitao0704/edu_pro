"""长期记忆管理 — MySQL + Neo4j + Milvus"""

from typing import List, Optional
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.model.entities import RiskScoreRecord


class LongTermMemory:
    """长期记忆管理器"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def archive_rating_record(
        self,
        customer_id: int,
        dimension_scores: dict,
        total_score: float,
        risk_level: str,
        circuit_breakers: List[dict],
        trigger_type: str = "manual",
    ) -> RiskScoreRecord:
        """归档研判评分记录"""
        record = RiskScoreRecord(
            customer_id=customer_id,
            rating_date=datetime.now(),
            basic_score=dimension_scores.get("basic", {}).get("score"),
            experience_score=dimension_scores.get("experience", {}).get("score"),
            risk_pref_score=dimension_scores.get("risk_pref", {}).get("score"),
            behavior_score=dimension_scores.get("behavior", {}).get("score"),
            total_score=total_score,
            risk_level=risk_level,
            detail_json=dimension_scores,
            circuit_breakers=circuit_breakers,
            trigger_type=trigger_type,
        )
        self.db.add(record)
        await self.db.flush()
        return record

    async def get_rating_history(self, customer_id: int, limit: int = 10) -> List[RiskScoreRecord]:
        """获取历史评分记录"""
        stmt = (
            select(RiskScoreRecord)
            .where(RiskScoreRecord.customer_id == customer_id)
            .order_by(RiskScoreRecord.create_time.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
