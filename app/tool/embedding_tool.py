"""
Embedding Tool — 文本向量化
调用 Ollama 本地 Embedding 模型（bge-m3）
"""

from typing import Optional
import httpx

from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger("tool.embedding")
settings = get_settings()


class EmbeddingTool:
    """文本 Embedding 生成工具（Ollama）"""

    def __init__(self):
        self.base_url = settings.llm.ollama_embed_url  # http://192.168.110.59:11434
        self.model = settings.llm.ollama_model_embedding  # bge-m3
        self.dim = settings.milvus.dim  # 1024
        self.timeout = settings.llm.openai_timeout

    async def encode(self, text: str) -> list[float]:
        """
        单条文本向量化

        Args:
            text: 待编码文本
        Returns:
            1024 维浮点向量
        """
        result = await self.encode_batch([text])
        return result[0]

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
