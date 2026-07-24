"""Session Context Store — Redis-backed persistent session context.

Thread-safe, survives service restarts. Falls back to in-memory dict when Redis is
unavailable (with a warning log).
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# TTL for session context in Redis (7 days — matches typical session lifecycle)
_SESSION_TTL = timedelta(days=7)


class SessionContextStore:
    """Owner-scoped context cache backed by Redis with in-memory fallback.

    Session context persists across service restarts via Redis. Each session's
    context is stored under the key ``session_ctx:{session_id}`` and is scoped
    to the owning actor.
    """

    # In-memory fallback for when Redis is unavailable
    _contexts: dict[str, dict[str, Any]] = {}
    _redis_available: bool | None = None  # None = not yet checked

    def _redis_key(self, session_id: str) -> str:
        return f"session_ctx:{session_id}"

    async def _get_redis(self):
        """Lazily get Redis connection (async, non-blocking check)."""
        try:
            from app.config.database import get_redis
            redis = await get_redis()
            # Quick health check
            await redis.ping()
            self.__class__._redis_available = True
            return redis
        except Exception:
            if self.__class__._redis_available is not False:
                logger.warning(
                    "Redis 不可用，SessionContext 回退到进程内存（重启丢失）"
                )
            self.__class__._redis_available = False
            return None

    async def get(self, session_id: str, actor_id: int) -> dict[str, Any]:
        """Get session context, preferring Redis, falling back to memory."""
        redis = await self._get_redis()
        if redis:
            try:
                raw = await redis.get(self._redis_key(session_id))
                if raw:
                    stored = json.loads(raw)
                    if stored.get("actor_id") == actor_id:
                        return deepcopy(stored.get("context", {}))
            except Exception as exc:
                logger.warning("Redis 读取 session context 失败: %s", exc)

        # Fallback to in-memory
        stored = self._contexts.get(session_id)
        if not stored or stored["actor_id"] != actor_id:
            return {}
        return deepcopy(stored["context"])

    async def update(
        self,
        session_id: str,
        actor_id: int,
        entities: dict[str, Any],
        **values: Any,
    ) -> dict[str, Any]:
        """Update session context in Redis (with in-memory fallback)."""
        existing = await self.get(session_id, actor_id)
        context = {
            **existing,
            **values,
            "entities": {**existing.get("entities", {}), **entities},
            "updated_at": datetime.now().isoformat(),
        }
        payload = {"actor_id": actor_id, "context": context}

        redis = await self._get_redis()
        if redis:
            try:
                await redis.setex(
                    self._redis_key(session_id),
                    int(_SESSION_TTL.total_seconds()),
                    json.dumps(payload, ensure_ascii=False, default=str),
                )
            except Exception as exc:
                logger.warning("Redis 写入 session context 失败: %s", exc)

        # Always update in-memory as backup
        self._contexts[session_id] = payload
        return deepcopy(context)

    async def delete(self, session_id: str) -> None:
        """Remove session context from Redis and memory."""
        redis = await self._get_redis()
        if redis:
            try:
                await redis.delete(self._redis_key(session_id))
            except Exception as exc:
                logger.warning("Redis 删除 session context 失败: %s", exc)
        self._contexts.pop(session_id, None)
