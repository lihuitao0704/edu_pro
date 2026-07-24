"""
Embedding Tool — 文本向量化
调用 Ollama 本地 Embedding 模型（bge-m3）
支持 Redis 缓存 query→embedding 映射，减少重复计算
"""

import hashlib
import json
from typing import Optional
import httpx

from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger("tool.embedding")
settings = get_settings()

# Embedding 缓存 TTL（秒）
EMBEDDING_CACHE_TTL = 3600  # 1小时


class EmbeddingTool:
    """文本 Embedding 生成工具（Ollama + Redis 缓存）"""

    def __init__(self):
        self.base_url = settings.llm.ollama_embed_url
        self.model = settings.llm.ollama_model_embedding
        self.dim = settings.milvus.dim
        self.timeout = settings.llm.openai_timeout

    @staticmethod
    def _cache_key(text: str) -> str:
        """生成缓存 key：embed:{model}:{md5(text)}"""
        text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
        return f"embed:{settings.llm.ollama_model_embedding}:{text_hash}"

    async def _get_cached(self, text: str) -> Optional[list[float]]:
        """从 Redis 读取缓存的 embedding"""
        try:
            from app.config.database import get_redis
            r = await get_redis()
            cached = await r.get(self._cache_key(text))
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        return None

    async def _set_cache(self, text: str, embedding: list[float]) -> None:
        """写入 Redis 缓存"""
        try:
            from app.config.database import get_redis
            r = await get_redis()
            await r.setex(
                self._cache_key(text),
                EMBEDDING_CACHE_TTL,
                json.dumps(embedding),
            )
        except Exception:
            pass

    async def encode(self, text: str) -> list[float]:
        """
        单条文本向量化（带 Redis 缓存）

        Args:
            text: 待编码文本
        Returns:
            1024 维浮点向量
        """
        # 1. 先查缓存
        cached = await self._get_cached(text)
        if cached:
            logger.info(f"Embedding 缓存命中 | text_len={len(text)}")
            return cached

        # 2. 缓存未命中，调用 Ollama
        result = await self.encode_batch([text])
        embedding = result[0]

        # 3. 写入缓存
        await self._set_cache(text, embedding)
        return embedding

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """
        批量文本向量化（Ollama API）

        Args:
            texts: 文本列表
        Returns:
            向量列表（顺序与输入一致）
        """
        if not texts:
            return []

        # 过滤空文本
        cleaned = [t.strip() if t.strip() else " " for t in texts]

        try:
            # Ollama Embedding API
            url = f"{self.base_url}/api/embed"
            payload = {
                "model": self.model,
                "input": cleaned,
            }

            # 禁用自动代理检测
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()

            # Ollama 返回格式：{"embeddings": [[...], [...], ...]}
            embeddings = result.get("embeddings", [])

            if not embeddings:
                raise ValueError("Ollama 返回的 embeddings 为空")

            logger.info(
                f"Embedding 生成成功 | model={self.model} | "
                f"count={len(embeddings)} | dim={len(embeddings[0]) if embeddings else 0}"
            )
            return embeddings

        except Exception as e:
            logger.error(f"Embedding 生成失败: {e}")
            raise

    @property
    def dimension(self) -> int:
        """返回向量维度"""
        return self.dim


# 全局单例
_embedding_tool: Optional[EmbeddingTool] = None


def get_embedding_tool() -> EmbeddingTool:
    """获取 Embedding 工具单例"""
    global _embedding_tool
    if _embedding_tool is None:
        _embedding_tool = EmbeddingTool()
    return _embedding_tool
