"""
RAG Service — 检索增强生成管道
完整 RAG 流程：Query Embedding → Milvus 粗排 → LLM Reranker 精排 → Score 过滤 → 关联元数据
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.tool.embedding_tool import get_embedding_tool
from app.tool.milvus_tool import get_milvus_tool, COLLECTION_CONFIGS
from app.tool.reranker_tool import get_reranker_tool
from app.model.entities import FinKnowledgeMeta
from app.utils.logger import get_logger

logger = get_logger("service.rag")

# 意图到 Milvus 集合的映射
INTENT_TO_COLLECTION = {
    "faq": "faq_knowledge",
    "product_inquiry": "product_knowledge",
    "policy_interpretation": "policy_knowledge",
}

# 各集合的检索配置
RETRIEVE_CONFIGS = {
    "faq_knowledge": {"top_k": 5, "rerank_top_n": 3, "threshold": 0.75},
    "product_knowledge": {"top_k": 10, "rerank_top_n": 5, "threshold": 0.7},
    "policy_knowledge": {"top_k": 10, "rerank_top_n": 5, "threshold": 0.7},
}


class RAGService:
    """RAG 检索增强生成服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedding_tool = get_embedding_tool()
        self.milvus_tool = get_milvus_tool()
        self.reranker_tool = get_reranker_tool()

    async def retrieve(
        self,
        query: str,
        knowledge_type: str,
        top_k: Optional[int] = None,
    ) -> list[dict]:
        """
        完整 RAG 检索流程

        Args:
            query: 用户查询
            knowledge_type: 知识类型（faq_knowledge / product_knowledge / policy_knowledge）
            top_k: 可选覆盖 TopK
        Returns:
            检索结果列表，每项包含 content, metadata, score, source_info
        """
        config = RETRIEVE_CONFIGS.get(knowledge_type, RETRIEVE_CONFIGS["product_knowledge"])
        if top_k:
            config = {**config, "top_k": top_k}

        # 1. 生成查询向量
        query_embedding = await self.embedding_tool.encode(query)

        # 2. Milvus 粗排检索
        raw_results = self.milvus_tool.search(
            collection_name=knowledge_type,
            query_vector=query_embedding,
            top_k=config["top_k"],
            output_fields=["content", "metadata"],
        )

        if not raw_results:
            logger.info(f"RAG 检索无结果 | query={query[:30]}... | collection={knowledge_type}")
            return []

        # 3. LLM Reranker 精排
        reranked = await self.reranker_tool.rerank(
            query=query,
            documents=raw_results,
            top_n=config["rerank_top_n"],
        )

        # 4. Score 过滤（降低阈值，保留更多结果）
        # 原阈值 0.7 太高，改为 0.3 以保留更多相关结果
        filtered = [r for r in reranked if r.get("score", 0) >= 0.3]

        # 如果过滤后为空，但 reranked 有结果，至少保留 top 1
        if not filtered and reranked:
            logger.warning(f"RAG 过滤后无结果，保留 reranked top1 | query={query[:30]}...")
            filtered = reranked[:1]

        # 5. 关联元数据（来源信息）
        for r in filtered:
            metadata = r.get("metadata", {})
            source_id = metadata.get("source_id")
            if source_id:
                source_info = await self._get_source_info(source_id)
                r["source_info"] = source_info
            else:
                r["source_info"] = {
                    "title": metadata.get("title", "未知来源"),
                    "source_file": metadata.get("source", ""),
                }

        logger.info(
            f"RAG 检索完成 | query={query[:30]}... | "
            f"collection={knowledge_type} | "
            f"粗排={len(raw_results)} → 精排={len(reranked)} → 过滤={len(filtered)}"
        )
        return filtered

    async def _get_source_info(self, source_id: int) -> dict:
        """从 MySQL 获取知识元数据"""
        try:
            stmt = select(FinKnowledgeMeta).where(FinKnowledgeMeta.id == source_id)
            result = await self.db.execute(stmt)
            meta = result.scalar_one_or_none()
            if meta:
                return {"title": meta.title, "source_file": meta.source_file or ""}
        except Exception as e:
            logger.warning(f"获取知识元数据失败 | source_id={source_id} | error={e}")
        return {"title": "未知来源", "source_file": ""}


# 全局单例（需要 db session，通过工厂方法获取）
def get_rag_service(db: AsyncSession) -> RAGService:
    """获取 RAG 服务实例"""
    return RAGService(db)
