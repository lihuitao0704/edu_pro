"""Customer search, detail, and holding APIs for role workspaces."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.security.authorization import require_roles
from app.utils.response import success

router = APIRouter()
EMPLOYEE_ROLES = ("理财顾问", "客户经理", "风控专员", "管理员")


@router.get("")
async def list_customers(
    keyword: str = "",
    risk_level: str = "",
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_roles(*EMPLOYEE_ROLES)),
):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    filters = ["u.user_type = 'CUSTOMER'"]
    params = {
        "keyword": f"%{keyword}%",
        "offset": (page - 1) * page_size,
        "limit": page_size,
    }
    if keyword:
        filters.append(
            "(u.real_name LIKE :keyword OR u.username LIKE :keyword OR u.phone LIKE :keyword)"
        )
    if risk_level:
        filters.append("p.risk_level = :risk_level")
        params["risk_level"] = risk_level
    where = " AND ".join(filters)

    count_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM sys_user u "
            "LEFT JOIN fin_customer_profile p ON p.customer_id = u.id "
            f"WHERE {where}"
        ),
        params,
    )
    rows_result = await db.execute(
        text(
            "SELECT u.id AS customer_id, u.username, u.real_name, u.phone, u.age, "
            "u.customer_level, p.risk_level, p.risk_score, p.total_assets, "
            "p.confidence_score, p.risk_flag "
            "FROM sys_user u "
            "LEFT JOIN fin_customer_profile p ON p.customer_id = u.id "
            f"WHERE {where} ORDER BY u.id LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    return success(
        data={
            "items": [_serialize_row(row) for row in rows_result.mappings().all()],
            "total": int(count_result.scalar() or 0),
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/{customer_id}")
async def get_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles(*EMPLOYEE_ROLES, "客户")),
):
    _ensure_customer_access(user, customer_id)
    result = await db.execute(
        text(
            "SELECT u.id AS customer_id, u.username, u.real_name, u.phone, u.email, "
            "u.age, u.education, u.occupation, u.customer_level, "
            "p.risk_level, p.risk_score, p.investment_experience, "
            "p.annual_income_range, p.total_assets, p.asset_allocation, "
            "p.product_preference, p.confidence_score, p.risk_flag "
            "FROM sys_user u LEFT JOIN fin_customer_profile p ON p.customer_id = u.id "
            "WHERE u.id = :customer_id AND u.user_type = 'CUSTOMER'"
        ),
        {"customer_id": customer_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="客户不存在")
    return success(data=_serialize_row(row))


@router.get("/{customer_id}/holdings")
async def get_customer_holdings(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles(*EMPLOYEE_ROLES, "客户")),
):
    _ensure_customer_access(user, customer_id)
    result = await db.execute(
        text(
            "SELECT h.id, h.customer_id, h.product_id, p.product_code, p.product_name, "
            "p.product_type, p.risk_level, h.shares, h.cost_amount, h.current_value, "
            "h.profit_loss, h.profit_ratio, h.status "
            "FROM fin_holdings h JOIN fin_product p ON p.id = h.product_id "
            "WHERE h.customer_id = :customer_id ORDER BY h.current_value DESC"
        ),
        {"customer_id": customer_id},
    )
    rows = [_serialize_row(row) for row in result.mappings().all()]
    return success(
        data={
            "items": rows,
            "total": len(rows),
            "total_value": sum(float(row.get("current_value") or 0) for row in rows),
        }
    )


def _serialize_row(row) -> dict:
    return {
        key: float(value) if value.__class__.__name__ == "Decimal" else value
        for key, value in dict(row).items()
    }


def _ensure_customer_access(user: dict, customer_id: int) -> None:
    if user.get("role") == "客户" and int(user.get("user_id") or 0) != customer_id:
        raise HTTPException(status_code=403, detail="客户只能访问本人数据")
