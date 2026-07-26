"""Shared account-role and token-session fingerprint helpers."""

from __future__ import annotations

import hashlib
import hmac

from app.config.settings import get_settings


EMPLOYEE_ROLES = {"理财顾问", "客户经理", "风控专员", "管理员"}


def role_from_record(user: dict) -> str:
    user_type = str(user.get("user_type") or "").upper()
    employee_role = str(user.get("employee_role") or "")
    if user_type == "CUSTOMER":
        return "客户"
    if user_type == "EMPLOYEE" and employee_role in EMPLOYEE_ROLES:
        return employee_role
    return ""


def auth_fingerprint(user: dict) -> str:
    """Create a non-reversible version claim that changes with account state."""
    material = "|".join(
        (
            str(user.get("id") or ""),
            str(user.get("username") or ""),
            str(user.get("password_hash") or ""),
            str(user.get("status") or ""),
            str(user.get("user_type") or ""),
            str(user.get("employee_role") or ""),
        )
    )
    secret = get_settings().jwt.secret_key.encode("utf-8")
    return hmac.new(secret, material.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
