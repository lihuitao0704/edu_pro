"""
JWT 认证中间件
=============
开发阶段：AUTH_MOCK_MODE=true 时跳过认证（兼容现有测试）
生产阶段：校验 Bearer Token，验证用户身份和角色
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.settings import get_settings

logger = logging.getLogger(__name__)
_settings = get_settings()

# 公开路径（无需认证）
PUBLIC_PATHS = {
    "/api/health",
    "/api/engine/test",  # 开发阶段保留，生产环境应移除
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
}

# 公开路径前缀
PUBLIC_PREFIXES = (
    "/static/",
    "/api/auth/",  # 登录/注册本身不需要认证
)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建 JWT access token"""
    to_encode = data.copy()
    # JWT 规范要求 sub 必须是字符串
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=_settings.jwt.expire_minutes)
    )
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
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
    """判断路径是否为公开路径"""
    if path in PUBLIC_PATHS:
        return True
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """JWT 认证中间件"""

    async def dispatch(self, request: Request, call_next):
        # Mock 模式：跳过所有认证（开发环境）
        if _settings.jwt.mock_mode:
            # 注入默认用户信息到 request state
            request.state.user = {
                "user_id": 0,
                "username": "mock_user",
                "role": "管理员",
            }
            return await call_next(request)

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
            user_id = int(payload.get("sub", 0))
        except (ValueError, TypeError):
            user_id = 0
        request.state.user = {
            "user_id": user_id,
            "username": payload.get("username", ""),
            "role": payload.get("role", "理财顾问"),
        }

        return await call_next(request)
