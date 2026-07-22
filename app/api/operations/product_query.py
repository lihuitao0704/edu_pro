"""
业务操作 API — 产品查询
负责人: LHG
"""

import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.model.schemas import ApiResponse

router = APIRouter()


@router.get("/product/list")
async def list_products(
    risk_level: str = None,
    product_type: str = None,
    db: AsyncSession = Depends(get_db),
):
    """
    产品列表查询（可按风险等级/产品类型筛选）
    """
    query = "SELECT * FROM fin_product WHERE status = '在售'"
    params = {}
    if risk_level:
        query += " AND risk_level = :rl"
        params["rl"] = risk_level
    if product_type:
        query += " AND product_type = :pt"
        params["pt"] = product_type
    query += " ORDER BY expected_return DESC"

    result = await db.execute(text(query), params)
    products = result.mappings().all()

    return {
        "code": 200,
        "message": "成功",
        "data": [
            {
                "product_id": p["id"],
                "product_code": p["product_code"],
                "product_name": p["product_name"],
                "product_type": p["product_type"],
                "risk_level": p["risk_level"],
                "expected_return": float(p["expected_return"] or 0),
                "min_amount": float(p["min_amount"] or 0),
            }
            for p in products
        ],
        "trace_id": uuid.uuid4().hex[:8],
    }


@router.get("/product/{product_id}")
async def query_product(product_id: int, db: AsyncSession = Depends(get_db)) -> ApiResponse:
    """
    查询产品详情（净值、风险等级、预期收益等）
    """
    result = await db.execute(
        text("SELECT * FROM fin_product WHERE id = :pid"),
        {"pid": product_id},
    )
    product = result.mappings().first()
    if not product:
        return ApiResponse(code=404, message="产品不存在", trace_id=uuid.uuid4().hex[:8])

    return ApiResponse(
        code=200,
        message="成功",
        data={
            "product_id": product["id"],
            "product_code": product["product_code"],
            "product_name": product["product_name"],
            "product_type": product["product_type"],
            "risk_level": product["risk_level"],
            "expected_return": float(product["expected_return"] or 0),
            "min_amount": float(product["min_amount"] or 0),
            "fund_manager": product["fund_manager"],
            "status": product["status"],
        },
        trace_id=uuid.uuid4().hex[:8],
    )
