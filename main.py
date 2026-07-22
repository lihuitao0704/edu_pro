"""
智能财富管家系统 - 主入口
FastAPI 应用启动
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config.settings import get_settings
from app.config.database import (
    init_db, close_redis, close_neo4j, close_milvus, get_redis,
)
from app.utils.logger import setup_logger, get_logger

# ---- 导入路由 ----
from app.api.profile import router as profile_router
from app.api.risk import router as risk_router
from app.api.advisor import router as advisor_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动
    setup_logger()
    logger = get_logger()
    logger.info("正在启动智能财富管家系统...")

    await init_db()
    logger.info("MySQL 数据库表初始化完成")

    await get_redis()
    logger.info("Redis 连接池预热完成")

    logger.info(f"LLM 模型: {settings.llm.openai_model_chat}")
    logger.info("系统启动完毕")

    yield

    # 关闭
    logger.info("正在关闭系统...")
    await close_redis()
    await close_neo4j()
    close_milvus()
    logger.info("系统已关闭")


app = FastAPI(
    title="智能财富管家系统",
    description="AI Agent 驱动的财富管理平台 — 客户画像 + 投顾助手",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 注册路由 ----
app.include_router(profile_router, prefix="/api/profile", tags=["客户画像"])
app.include_router(risk_router, prefix="/api/risk", tags=["风险评估"])
app.include_router(advisor_router, prefix="/api/chat", tags=["投顾对话"])


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "service": "wealth-manager",
            "version": "1.0.0",
            "databases": {
                "mysql": f"{settings.mysql.host}:{settings.mysql.port}/{settings.mysql.database}",
                "redis": f"{settings.redis.host}:{settings.redis.port}",
                "neo4j": settings.neo4j.uri,
                "milvus": f"{settings.milvus.host}:{settings.milvus.port}",
            },
            "llm_model": settings.llm.openai_model_chat,
            "auth_mode": "mock" if settings.jwt.mock_mode else "jwt",
        },
    }
