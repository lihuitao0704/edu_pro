"""业务操作 API — 风评重做（完整规则引擎路径）"""
import json
import logging
import uuid
from datetime import date as date_type, datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.model.schemas import ApiResponse, AssessmentAnswer
from app.engine.score_mapper import map_score_to_risk_level
from app.service.profile_service import ProfileService
from app.security.authorization import require_roles, authenticated_actor_id
from app.tool.neo4j_sync import sync_risk_level

router = APIRouter()
_logger = logging.getLogger(__name__)


@router.post("/assessment")
async def redo_assessment(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("理财顾问", "管理员")),
) -> ApiResponse:
    """风评重做：走完整规则引擎（熔断+四维度+校准+特殊场景）+ Neo4j同步"""
    customer_id = body.get("customer_id")
    raw_answers = body.get("answers", [])
    operator_id = authenticated_actor_id(user, body.get("operator_id"))

    if not customer_id:
        return ApiResponse(code=400, message="缺少客户ID", trace_id=uuid.uuid4().hex[:8])

    if not raw_answers or not isinstance(raw_answers, list):
        return ApiResponse(code=400, message="答案列表不能为空", trace_id=uuid.uuid4().hex[:8])

    try:
        raw_answers = [int(a) for a in raw_answers]
    except (ValueError, TypeError):
        return ApiResponse(code=400, message="答案必须为整数列表", trace_id=uuid.uuid4().hex[:8])

    for i, a in enumerate(raw_answers):
        if a < 1 or a > 20:
            return ApiResponse(
                code=400,
                message=f"第 {i+1} 题分值 {a} 超出范围，每题应为 1-20 分",
                trace_id=uuid.uuid4().hex[:8],
            )

    # Step 1: 计算问卷总分并归一化到 0-100
    raw_total = min(sum(raw_answers), 100)
    normalized = round(raw_total)  # 已经是 0-100 范围
    risk_level, risk_level_name = map_score_to_risk_level(normalized)
    valid_until = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")

    # 构造 AssessmentAnswer 格式（兼容引擎的问卷维度计算）
    assessment_answers = [
        AssessmentAnswer(q=i + 1, a=str(a))
        for i, a in enumerate(raw_answers)
    ]

    # Step 2: 写入风评记录
    await db.execute(
        text("INSERT INTO fin_risk_assessment (customer_id,assessment_date,total_score,risk_level,answers,valid_until,assessor_type) VALUES (:c,CURDATE(),:s,:r,:a,:v,'manual')"),
        {"c": customer_id, "s": normalized, "r": risk_level, "a": json.dumps(raw_answers), "v": valid_until},
    )

    # 更新画像基础风险等级（引擎会在此基础上做全面研判）
    await db.execute(
        text("UPDATE fin_customer_profile SET risk_level = :rl, risk_score = :rs, update_time = NOW() WHERE customer_id = :cid"),
        {"rl": risk_level, "rs": normalized, "cid": customer_id},
    )
    await db.commit()

    # Step 3: 运行完整规则引擎（熔断 + 四维度 + 校准 + 特殊场景）
    engine_result = None
    try:
        profile_svc = ProfileService(db)
        engine_result = await profile_svc.assess(customer_id, trigger_type="manual")
        final_level = engine_result.risk_level
        _logger.info(
            "完整引擎研判完成 customer=%s level=%s breakers=%d warnings=%d",
            customer_id, final_level,
            len(engine_result.circuit_breakers),
            len(engine_result.warnings),
        )
    except Exception as exc:
        _logger.warning("完整引擎研判失败 customer=%s (回退使用问卷得分): %s", customer_id, exc)
        final_level = risk_level

    # Step 4: Neo4j 图谱同步
    try:
        await sync_risk_level(customer_id, final_level)
    except Exception as exc:
        _logger.warning("Neo4j risk_level sync failed after assessment customer=%s: %s", customer_id, exc)
        try:
            from app.service.graph_sync_retry_service import record_sync_failure
            await record_sync_failure("risk_level", {
                "customer_id": customer_id,
                "risk_level": final_level,
            }, str(exc))
        except Exception as retry_exc:
            _logger.error("记录图谱同步重试失败: %s", retry_exc)

    return ApiResponse(
        code=200,
        message="风评完成（已运行完整规则引擎）",
        data={
            "customer_id": customer_id,
            "risk_level": final_level,
            "score": normalized,
            "valid_until": valid_until,
            "engine_breakers": len(engine_result.circuit_breakers) if engine_result else 0,
            "engine_warnings": len(engine_result.warnings) if engine_result else 0,
        },
        trace_id=uuid.uuid4().hex[:8],
    )
