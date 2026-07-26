"""
JWT 认证中间件
=============
所有受保护 API 均校验 Bearer Token。
AUTH_MOCK_MODE 仅用于兼容演示数据登录，不再提供匿名管理员身份。
"""

import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Request, Response
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.database import async_session_factory
from app.config.settings import get_settings
from app.security.session_identity import auth_fingerprint, role_from_record

logger = logging.getLogger(__name__)
_settings = get_settings()

# 公开路径（无需认证）
PUBLIC_PATHS = {
    "/api/health",
    "/api/health/live",
    "/api/health/ready",
    "/api/engine/test",  # 开发阶段保留，生产环境应移除
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/refresh",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
}

# 公开路径前缀
PUBLIC_PREFIXES: tuple[str, ...] = ()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建 JWT access token"""
    to_encode = data.copy()
    # JWT 规范要求 sub 必须是字符串
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta or timedelta(minutes=_settings.jwt.expire_minutes)
    )
    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(to_encode, _settings.jwt.secret_key, algorithm=_settings.jwt.algorithm)


def decode_access_token(token: str) -> Optional[dict]:
    """解码 JWT token，失败返回 None"""
    try:
        payload = jwt.decode(
            token,
            _settings.jwt.secret_key,
            algorithms=[_settings.jwt.algorithm],
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token 已过期")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Token 无效: {e}")
        return None


def _is_public_path(path: str) -> bool:
    # The Vue shell, history routes, and compiled assets must be reachable so
    # unauthenticated users can load the login page. API routes stay protected.
    if path != "/api" and not path.startswith("/api/"):
        return True
    """判断路径是否为公开路径"""
    if path in PUBLIC_PATHS:
        return True
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


async def _load_current_identity(user_id: int):
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT id, username, password_hash, user_type, employee_role, status "
                "FROM sys_user WHERE id = :id"
            ),
            {"id": user_id},
        )
        return result.mappings().first()


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """JWT 认证中间件"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 公开路径直接放行
        if _is_public_path(path):
            return await call_next(request)

        # 提取 Bearer Token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return Response(
                content='{"code": 401, "message": "缺少认证信息", "data": null, "trace_id": ""}',
                status_code=401,
                media_type="application/json",
            )

        token = auth_header[7:]  # 去掉 "Bearer " 前缀
        payload = decode_access_token(token)
        if payload is None:
            return Response(
                content='{"code": 401, "message": "Token 无效或已过期", "data": null, "trace_id": ""}',
                status_code=401,
                media_type="application/json",
            )

        # 将用户信息注入 request state
        try:
            user_id = int(payload.get("sub"))
        except (ValueError, TypeError):
            return Response(
                content='{"code": 401, "message": "Token 缺少有效用户身份", "data": null, "trace_id": ""}',
                status_code=401,
                media_type="application/json",
            )
        role = str(payload.get("role") or "")
        if user_id <= 0 or not role:
            return Response(
                content='{"code": 401, "message": "Token 身份信息不完整", "data": null, "trace_id": ""}',
                status_code=401,
                media_type="application/json",
            )
        try:
            current_user = await _load_current_identity(user_id)
        except Exception:
            logger.exception("认证状态查询失败")
            return Response(
                content='{"code": 503, "message": "认证服务暂时不可用", "data": null, "trace_id": ""}',
                status_code=503,
                media_type="application/json",
            )
        current_role = role_from_record(current_user or {})
        if (
            not current_user
            or str(current_user.get("status") or "") != "正常"
            or not current_role
        ):
            return Response(
                content='{"code": 401, "message": "账户不存在、已停用或身份异常", "data": null, "trace_id": ""}',
                status_code=401,
                media_type="application/json",
            )
        token_version = str(payload.get("av") or "")
        current_version = auth_fingerprint(current_user)
        if (
            current_role != role
            or str(current_user.get("username") or "")
            != str(payload.get("username") or "")
            or not token_version
            or not hmac.compare_digest(token_version, current_version)
        ):
            return Response(
                content='{"code": 401, "message": "账户信息已变更，请重新登录", "data": null, "trace_id": ""}',
                status_code=401,
                media_type="application/json",
            )
        request.state.user = {
            "user_id": user_id,
            "username": current_user.get("username") or "",
            "role": current_role,
        }

        return await call_next(request)
