"""中期记忆 — 画像缓存（Cache-Aside 模式）"""

import json
from typing import Optional
from app.config.database import get_redis
from app.config.settings import get_settings

settings = get_settings()


class ProfileCache:
    """画像缓存管理器"""

    @staticmethod
    def _key(customer_id: int) -> str:
        return f"profile:{customer_id}"

    async def get(self, customer_id: int) -> Optional[dict]:
        """从 Redis 获取画像缓存"""
        r = await get_redis()
        data = await r.get(self._key(customer_id))
        if data:
            return json.loads(data)
        return None

    async def set(self, customer_id: int, profile: dict, ttl: int = None) -> None:
        """写入画像缓存"""
        r = await get_redis()
        await r.set(
            self._key(customer_id),
            json.dumps(profile, ensure_ascii=False, default=str),
            ex=ttl or settings.redis.profile_ttl,
        )

    async def invalidate(self, customer_id: int) -> None:
        """失效画像缓存（风评更新、持仓变化、大额交易时触发）"""
        r = await get_redis()
        await r.delete(self._key(customer_id))

    async def exists(self, customer_id: int) -> bool:
        """检查缓存是否存在"""
        r = await get_redis()
        return await r.exists(self._key(customer_id)) > 0
