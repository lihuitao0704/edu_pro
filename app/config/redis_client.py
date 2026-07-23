"""
Redis 同步客户端 — 用于 NL2SQL 缓存等场景
"""

import redis
import logging

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

_redis_client = None


def get_redis_client() -> redis.Redis:
    """获取 Redis 同步客户端（懒加载单例）"""
    global _redis_client
    if _redis_client is None:
        try:
            settings = get_settings()
            _redis_client = redis.Redis(
                host=settings.redis.host,
                port=settings.redis.port,
                password=settings.redis.password or None,
                db=settings.redis.db,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            _redis_client.ping()
            logger.info("Redis 同步客户端连接成功")
        except Exception as e:
            logger.warning(f"Redis 连接失败，缓存功能不可用: {e}")
            _redis_client = None
    return _redis_client


def close_redis_client():
    """关闭 Redis 同步客户端"""
    global _redis_client
    if _redis_client:
        try:
            _redis_client.close()
        except Exception:
            pass
        _redis_client = None
