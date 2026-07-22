"""
向量嵌入工具 — 支持 Ollama 本地 BGE-M3 + OpenAI 云端嵌入
─────────────────────────────────────────────────────────
本机 BGE-M3:   Ollama → http://127.0.0.1:11434 → 维度 1024
远程 OpenAI:   text-embedding-3-small → 维度 1536
"""

import time
from typing import List
import httpx
from openai import OpenAI

from app.config.settings import get_settings

settings = get_settings()


class EmbeddingTool:
    """
    文本 → 向量嵌入

    优先级: Ollama 本地 > OpenAI 云端
    """

    def __init__(self):
        self.model_name = settings.llm.openai_model_embedding       # "bge-m3" 或 "text-embedding-3-small"
        self.ollama_url = settings.llm.ollama_embed_url             # http://192.168.110.59:11434
        self._is_ollama = self._detect_ollama()

    # ── 自动检测 ──────────────────────────────────────────

    def _detect_ollama(self) -> bool:
        """
        检测 Ollama 是否可用 + BGE-M3 是否已拉取
        探测顺序: 127.0.0.1 → 配置的远程地址
        """
        # 需要探测的地址列表
        urls = ["http://127.0.0.1:11434"]
        if self.ollama_url not in urls:
            urls.append(self.ollama_url)

        for url in urls:
            try:
                resp = httpx.get(f"{url}/api/tags", timeout=3)
                if resp.status_code != 200:
                    continue
                models = resp.json().get("models", [])
                for m in models:
                    if self.model_name in m.get("name", ""):
                        self.ollama_url = url  # 记住能用的地址
                        return True
            except Exception:
                continue
        return False

    @property
    def provider(self) -> str:
        """当前使用的嵌入服务"""
        return "ollama" if self._is_ollama else "openai"

    @property
    def dimension(self) -> int:
        """当前嵌入维度"""
        return 1024 if self._is_ollama else 1536

    # ── 核心方法 ──────────────────────────────────────────

    def embed(self, text: str) -> List[float]:
        """
        单条文本嵌入
        返回 float 列表，长度为 1024 (Ollama BGE-M3) 或 1536 (OpenAI)
        """
        if self._is_ollama:
            return self._embed_ollama(text)
        # 云端降级：DeepSeek 不支持 embedding，尝试用 OpenAI
        return self._embed_openai(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        批量文本嵌入
        """
        if self._is_ollama:
            return [self._embed_ollama(t) for t in texts]
        return self._embed_openai_batch(texts)

    # ── Ollama 本地嵌入 ───────────────────────────────────

    def _embed_ollama(self, text: str) -> List[float]:
        """
        Ollama 原生 API: POST /api/embeddings
        返回 1024 维向量
        """
        resp = httpx.post(
            f"{self.ollama_url}/api/embeddings",
            json={"model": f"{self.model_name}:latest", "prompt": text},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]

    # ── OpenAI 云端嵌入 (含 Ollama 兼容端点) ──────────────

    def _embed_openai(self, text: str) -> List[float]:
        """OpenAI 兼容 API"""
        client = OpenAI(
            api_key=settings.llm.openai_api_key,
            base_url=settings.llm.openai_base_url,
            timeout=settings.llm.openai_timeout,
            max_retries=settings.llm.openai_max_retries,
        )
        resp = client.embeddings.create(model=self.model_name, input=text)
        return resp.data[0].embedding

    def _embed_openai_batch(self, texts: List[str]) -> List[List[float]]:
        """OpenAI 批量嵌入"""
        client = OpenAI(
            api_key=settings.llm.openai_api_key,
            base_url=settings.llm.openai_base_url,
            timeout=settings.llm.openai_timeout,
            max_retries=settings.llm.openai_max_retries,
        )
        resp = client.embeddings.create(model=self.model_name, input=texts)
        return [r.embedding for r in resp.data]


# ══════════════════════════════════════════════════════════
# 测试 & 使用说明
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    tool = EmbeddingTool()

    print(f"嵌入服务: {tool.provider}")
    print(f"模型名称: {tool.model_name}")
    print(f"向量维度: {tool.dimension}")

    # 单条嵌入
    vec = tool.embed("智能财富管家系统")
    print(f"单条嵌入: '{'智能财富管家系统'}' → [{vec[0]:.4f}, {vec[1]:.4f}, ...] ({len(vec)}维)")

    # 批量嵌入
    texts = ["风险评估", "产品推荐", "资产配置"]
    vecs = tool.embed_batch(texts)
    for t, v in zip(texts, vecs):
        print(f"  '{t}' → [{v[0]:.4f}, {v[1]:.4f}, ...] ({len(v)}维)")
