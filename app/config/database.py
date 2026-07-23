"""
数据库连接管理
MySQL (SQLAlchemy Async) / Redis / Neo4j / Milvus / MinIO
"""

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from neo4j import AsyncGraphDatabase
from pymilvus import connections as milvus_connections
from typing import Optional

from app.config.settings import get_settings

settings = get_settings()


# ==================== MySQL（SQLAlchemy Async） ====================

_mysql_url = (
    f"mysql+aiomysql://{settings.mysql.user}:{settings.mysql.password}"
    f"@{settings.mysql.host}:{settings.mysql.port}/{settings.mysql.database}"
    f"?charset=utf8mb4"
)

engine = create_async_engine(
    _mysql_url,
    pool_size=settings.mysql.pool_size,
    pool_recycle=settings.mysql.pool_recycle,
    echo=settings.mysql.echo,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# 同步 session factory（供 NL2SQL 等需要同步操作的模块使用）
_sync_mysql_url = (
    f"mysql+pymysql://{settings.mysql.user}:{settings.mysql.password}"
    f"@{settings.mysql.host}:{settings.mysql.port}/{settings.mysql.database}"
    f"?charset=utf8mb4"
)

_sync_engine = create_engine(
    _sync_mysql_url,
    pool_size=settings.mysql.pool_size,
    pool_recycle=settings.mysql.pool_recycle,
    echo=settings.mysql.echo,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=_sync_engine,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """ORM 基类，所有实体模型继承此类"""
    pass


async def get_db():
    """获取数据库会话（FastAPI 依赖注入用）"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """初始化基础表；已有表的字段变更由 migrations/ 中的版本化脚本负责。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Versioned DDL lives in migrations/ and is never executed at startup.


# ==================== Redis ====================

_redis_pool: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """获取 Redis 连接"""
    global _redis_pool
    if _redis_pool is None:
        # 构建 Redis URL，包含密码（如果有）
        password = settings.redis.password
        if password:
            redis_url = (
                f"redis://:{password}@{settings.redis.host}:{settings.redis.port}/{settings.redis.db}"
            )
        else:
            redis_url = (
                f"redis://{settings.redis.host}:{settings.redis.port}/{settings.redis.db}"
            )
        _redis_pool = aioredis.from_url(
            redis_url,
            max_connections=settings.redis.max_connections,
            decode_responses=True,
        )
    return _redis_pool


async def close_redis():
    """关闭 Redis 连接"""
    global _redis_pool
    if _redis_pool:
        await _redis_pool.close()
        _redis_pool = None


# ==================== Neo4j ====================

_neo4j_driver: Optional[object] = None


def get_neo4j_driver():
    """获取 Neo4j 驱动"""
    global _neo4j_driver
    if _neo4j_driver is None:
        _neo4j_driver = AsyncGraphDatabase.driver(
            settings.neo4j.uri,
            auth=(settings.neo4j.user, settings.neo4j.password),
            max_connection_lifetime=3600,
            max_connection_pool_size=10,
            connection_acquisition_timeout=settings.neo4j.timeout,
        )
    return _neo4j_driver


async def close_neo4j():
    """关闭 Neo4j 连接"""
    global _neo4j_driver
    if _neo4j_driver:
        await _neo4j_driver.close()
        _neo4j_driver = None


# ==================== Milvus ====================

_milvus_connected: bool = False


def init_milvus():
    """初始化 Milvus 连接"""
    global _milvus_connected
    if not _milvus_connected:
        try:
            milvus_connections.connect(
                alias="default",
                host=settings.milvus.host,
                port=settings.milvus.port,
            )
            _milvus_connected = True
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Milvus 连接失败（不影响核心服务）: {e}")
            _milvus_connected = False


def close_milvus():
    """关闭 Milvus 连接"""
    global _milvus_connected
    if _milvus_connected:
        milvus_connections.disconnect("default")
        _milvus_connected = False


# ==================== MinIO ====================

_minio_client = None


def get_minio_client():
    """获取 MinIO 客户端（懒加载，避免强依赖）"""
    global _minio_client
    if _minio_client is None:
        from minio import Minio
        _minio_client = Minio(
            settings.minio.endpoint,
            access_key=settings.minio.access_key,
            secret_key=settings.minio.secret_key,
            secure=settings.minio.secure,
        )
    return _minio_client


# ==================== MySQL 同步引擎（NL2SQL 用） ====================
# 复用顶部已定义的 SessionLocal，不再重复创建
# 如需在同步代码中使用，直接 from app.config.database import SessionLocal
