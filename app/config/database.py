"""
数据库连接管理
MySQL（SQLAlchemy）、Redis、Neo4j、Milvus、MinIO 连接池
"""

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from neo4j import AsyncGraphDatabase
from pymilvus import connections as milvus_connections, Collection
from minio import Minio
from typing import Optional

from app.config.settings import get_settings

settings = get_settings()


# ==================== MySQL（SQLAlchemy Async） ====================

# 构建异步数据库 URL
_mysql_url = settings.mysql.url.replace("mysql+pymysql://", "mysql+aiomysql://")
_mysql_url = _mysql_url.replace("?charset=utf8mb4", "")

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


class Base(DeclarativeBase):
    """ORM 基类，所有实体模型继承此类"""
    pass


async def get_db() -> AsyncSession:
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
    """初始化数据库表（首次运行时创建所有表）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ==================== Redis ====================

_redis_pool: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """获取 Redis 连接"""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            settings.redis.url,
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
        milvus_connections.connect(
            alias="default",
            host=settings.milvus.host,
            port=settings.milvus.port,
        )
        _milvus_connected = True


def get_milvus_collection(collection_name: str) -> Collection:
    """获取 Milvus 集合"""
    init_milvus()
    return Collection(collection_name)


def close_milvus():
    """关闭 Milvus 连接"""
    global _milvus_connected
    if _milvus_connected:
        milvus_connections.disconnect("default")
        _milvus_connected = False


# ==================== MinIO ====================

_minio_client: Optional[Minio] = None


def get_minio_client() -> Minio:
    """获取 MinIO 客户端"""
    global _minio_client
    if _minio_client is None:
        _minio_client = Minio(
            settings.minio.endpoint,
            access_key=settings.minio.access_key,
            secret_key=settings.minio.secret_key,
            secure=settings.minio.secure,
        )
        # 确保 bucket 存在
        if not _minio_client.bucket_exists(settings.minio.bucket_docs):
            _minio_client.make_bucket(settings.minio.bucket_docs)
    return _minio_client
