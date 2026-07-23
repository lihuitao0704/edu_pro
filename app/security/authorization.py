"""Role-based API authorization bound to the authenticated request."""

from collections.abc import Callable

from fastapi import HTTPException, Request


def get_request_role(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    return str(user.get("role") or "")


def enforce_customer_scope(user: dict, customer_id: int) -> int:
    """Prevent a customer token from reading or mutating another customer."""
    target_id = int(customer_id)
    if (
        str(user.get("role") or "") == "客户"
        and int(user.get("user_id") or 0) != target_id
    ):
        raise HTTPException(status_code=403, detail="客户只能访问本人数据")
    return target_id


def authenticated_actor_id(user, fallback: int = 0) -> int:
    """Use the JWT actor for HTTP calls; keep trusted internal Agent calls compatible."""
    if isinstance(user, dict):
        return int(user.get("user_id") or 0)
    return int(fallback or 0)


def require_roles(*roles: str) -> Callable:
    allowed = set(roles)

    async def dependency(request: Request) -> dict:
        user = getattr(request.state, "user", None) or {}
        role = str(user.get("role") or "")
        if role not in allowed:
            raise HTTPException(status_code=403, detail="当前角色无权执行此操作")
        return user

    return dependency
