"""业务操作 API — 风评重做"""
import json
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

    # 校验答案：必须是非空列表，每个元素为整数
    if not answers or not isinstance(answers, list):
        return ApiResponse(code=400, message="答案列表不能为空", trace_id=uuid.uuid4().hex[:8])

    try:
        answers = [int(a) for a in answers]
    except (ValueError, TypeError):
        return ApiResponse(code=400, message="答案必须为整数列表", trace_id=uuid.uuid4().hex[:8])

    # 校验每题分值范围（每题 1-20 分）
    for i, a in enumerate(answers):
        if a < 1 or a > 20:
            return ApiResponse(
                code=400,
                message=f"第 {i+1} 题分值 {a} 超出范围，每题应为 1-20 分",
                trace_id=uuid.uuid4().hex[:8],
            )

    # 评分：各题分值求和，上限100
    total_score = min(sum(answers), 100)
    risk_level = calc_risk_level(total_score)
    valid_until = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")

    await db.execute(
        text("INSERT INTO fin_risk_assessment (customer_id,assessment_date,total_score,risk_level,answers,valid_until,assessor_type) VALUES (:c,CURDATE(),:s,:r,:a,:v,'manual')"),
        {"c": customer_id, "s": total_score, "r": risk_level, "a": json.dumps(answers), "v": valid_until},
    )
    await db.commit()
    return ApiResponse(code=200, message="风评完成", data={"customer_id": customer_id, "risk_level": risk_level, "score": total_score, "valid_until": valid_until}, trace_id=uuid.uuid4().hex[:8])
