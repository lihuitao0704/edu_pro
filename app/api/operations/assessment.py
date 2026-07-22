"""业务操作 API — 风评重做"""
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.model.schemas import ApiResponse

router = APIRouter()

# 简化评分映射
def calc_risk_level(score: int) -> str:
    if score <= 20: return "C1"
    if score <= 40: return "C2"
    if score <= 60: return "C3"
    if score <= 80: return "C4"
    return "C5"


@router.post("/assessment")
async def redo_assessment(body: dict, db: AsyncSession = Depends(get_db)) -> ApiResponse:
    """风评重做：根据答题计算风险等级，写入记录"""
    customer_id = body.get("customer_id")
    answers = body.get("answers", [])
    operator_id = body.get("operator_id")

    if not customer_id:
        return ApiResponse(code=400, message="缺少客户ID", trace_id=uuid.uuid4().hex[:8])

    # 简化：根据答案数量计算分数（Mock）
    total_score = min(len(answers) * 15, 100)
    risk_level = calc_risk_level(total_score)
    valid_until = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")

    await db.execute(
        text("INSERT INTO fin_risk_assessment (customer_id,assessment_date,total_score,risk_level,answers,valid_until,assessor_type) VALUES (:c,CURDATE(),:s,:r,:a,:v,'manual')"),
        {"c": customer_id, "s": total_score, "r": risk_level, "a": str(answers), "v": valid_until},
    )
    await db.commit()
    return ApiResponse(code=200, message="风评完成", data={"customer_id": customer_id, "risk_level": risk_level, "score": total_score, "valid_until": valid_until}, trace_id=uuid.uuid4().hex[:8])
