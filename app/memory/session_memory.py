"""短期记忆 — Redis 会话管理 + 归档"""

import json
from typing import List
from app.config.database import get_redis
from app.config.settings import get_settings

settings = get_settings()


class SessionMemory:
    """会话记忆管理器（含归档能力）"""

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

        # 从新到旧累计 token，超过预算则截断（用 append+reverse 代替 insert(0) 避免 O(n²)）
        accumulated = 0
        result = []
        for msg in reversed(messages):
            estimated = max(len(msg["content"]) // 2, 1)  # 粗略估算：2 字符 ≈ 1 token，至少 1 token
            if accumulated + estimated > max_tokens:
                break
            result.append(msg)
            accumulated += estimated
        result.reverse()

        return result

    async def get_all_messages(self) -> List[dict]:
        """获取所有消息（不截断，归档用）"""
        r = await self._get_redis()
        raw = await r.lrange(self.key, 0, -1)
        return [json.loads(m) for m in raw]

    async def clear(self) -> None:
        """清空会话"""
        r = await self._get_redis()
        await r.delete(self.key)

    async def extend_ttl(self) -> None:
        """续期会话 TTL"""
        r = await self._get_redis()
        await r.expire(self.key, settings.redis.session_ttl)

    async def archive(self, db, user_id: int, agent_type: str = "advisor") -> int:
        """
        将当前会话消息归档到 MySQL conversation_archive 表。

        Args:
            db: AsyncSession 数据库会话
            user_id: 用户ID（理财顾问）
            agent_type: Agent类型标识
        Returns:
            归档的消息条数
        """
        from app.model.entities import ConversationArchive
        messages = await self.get_all_messages()
        if not messages:
            return 0

        # 去重：检查该 session 是否已经归档过
        from sqlalchemy import select, func
        existing_count = await db.execute(
            select(func.count()).select_from(ConversationArchive).where(
                ConversationArchive.session_id == self.session_id
            )
        )
        existing = existing_count.scalar() or 0
        if existing >= len(messages):
            # 已全部归档过，直接清理 Redis
            await self.clear()
            return 0

        count = 0
        for i, msg in enumerate(messages):
            if i < existing:
                continue  # 跳过已归档的消息
            record = ConversationArchive(
                session_id=self.session_id,
                user_id=user_id,
                agent_type=agent_type,
                role=msg.get("role", "user"),
                content=msg.get("content", ""),
            )
            db.add(record)
            count += 1

        await db.flush()
        # flush 成功后再清理 Redis（如果后续 commit 失败，数据已在 MySQL 中）
        await self.clear()
        return count
