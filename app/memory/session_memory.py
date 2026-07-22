"""短期记忆 — Redis 会话管理"""

import json
from typing import List
from app.config.database import get_redis
from app.config.settings import get_settings

settings = get_settings()


class SessionMemory:
    """会话记忆管理器"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.key = f"session:{session_id}:messages"
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            self._redis = await get_redis()
        return self._redis

    async def add_message(self, role: str, content: str) -> None:
        """添加一条消息"""
        r = await self._get_redis()
        msg = json.dumps({"role": role, "content": content}, ensure_ascii=False)
        await r.rpush(self.key, msg)
        await r.expire(self.key, settings.redis.session_ttl)

    async def get_messages(self, max_tokens: int = 4096) -> List[dict]:
        """获取历史消息（按 token 预算截断）"""
        r = await self._get_redis()
        raw = await r.lrange(self.key, 0, -1)

        messages = [json.loads(m) for m in raw]

        # 从旧到新累计 token，超过预算则截断
        accumulated = 0
        result = []
        for msg in reversed(messages):
            estimated = len(msg["content"]) // 2  # 粗略估算：2 字符 ≈ 1 token
            if accumulated + estimated > max_tokens:
                break
            result.insert(0, msg)
            accumulated += estimated

        return result

    async def clear(self) -> None:
        """清空会话"""
        r = await self._get_redis()
        await r.delete(self.key)

    async def extend_ttl(self) -> None:
        """续期会话 TTL"""
        r = await self._get_redis()
        await r.expire(self.key, settings.redis.session_ttl)
