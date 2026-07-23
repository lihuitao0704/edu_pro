"""
认证 API — 登录 / 刷新 Token / 获取当前用户
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.config.settings import get_settings
from app.middleware.auth import create_access_token, decode_access_token
from app.utils.response import success, error

router = APIRouter()
_settings = get_settings()


# ==================== 请求/响应模型 ====================

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64, description="用户名")
    password: str = Field(..., min_length=1, max_length=128, description="密码")


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 秒
    user: dict


class UserInfo(BaseModel):
    user_id: int
    username: str
    role: str


# ==================== 接口 ====================

@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    用户登录，返回 JWT Token

    生产环境应校验密码哈希（bcrypt / argon2）
    当前为简化实现，仅校验用户名存在
    """
    try:
        result = await db.execute(
            text("SELECT id, username, role, real_name FROM sys_user WHERE username = :u"),
            {"u": body.username},
        )
        user = result.mappings().first()
    except Exception as e:
        return error(code=500, message=f"数据库查询失败: {str(e)[:100]}")

    if not user:
        return error(code=401, message="用户名或密码错误")

    # TODO: 生产环境必须校验密码哈希
    # from passlib.context import CryptContext
    # if not pwd_context.verify(body.password, user["password_hash"]):
    #     return error(code=401, message="用户名或密码错误")

    # 签发 Token
    expires = timedelta(minutes=_settings.jwt.expire_minutes)
    token = create_access_token(
        data={
            "sub": user["id"],
            "username": user["username"],
            "role": user.get("role", "理财顾问"),
            "real_name": user.get("real_name", ""),
        },
        expires_delta=expires,
    )

    return success(data={
        "access_token": token,
        "token_type": "bearer",
        "expires_in": int(expires.total_seconds()),
        "user": {
            "user_id": user["id"],
            "username": user["username"],
            "role": user.get("role", "理财顾问"),
            "real_name": user.get("real_name", ""),
        },
    })


@router.post("/refresh")
async def refresh_token(request: Request):
    """刷新 Token（用旧 Token 换新 Token）"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return error(code=401, message="缺少 Token")

    token = auth_header[7:]
    payload = decode_access_token(token)
    if payload is None:
        return error(code=401, message="Token 无效或已过期")

    # 签发新 Token
    expires = timedelta(minutes=_settings.jwt.expire_minutes)
    new_token = create_access_token(
        data={
            "sub": str(payload.get("sub", 0)),
            "username": payload.get("username"),
            "role": payload.get("role", "理财顾问"),
        },
        expires_delta=expires,
    )

    return success(data={
        "access_token": new_token,
        "token_type": "bearer",
        "expires_in": int(expires.total_seconds()),
    })


@router.get("/me")
async def get_current_user(request: Request):
    """获取当前登录用户信息"""
    user = getattr(request.state, "user", None)
    if not user:
        return error(code=401, message="未登录")
    return success(data=user)
