"""
Knowledge Service — 知识库业务逻辑
文档上传入库 / 列表查询 / 删除 / 独立检索
"""

from typing import Optional
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.tool.document_parser import get_document_parser
from app.tool.embedding_tool import get_embedding_tool
from app.tool.milvus_tool import get_milvus_tool
from app.tool.minio_tool import get_minio_tool
from app.model.entities import FinKnowledgeMeta
from app.utils.logger import get_logger

logger = get_logger("service.knowledge")

# 知识类型到 Milvus 集合的映射
KNOWLEDGE_TYPE_TO_COLLECTION = {
    "FAQ": "faq_knowledge",
    "产品说明": "product_knowledge",
    "政策法规": "policy_knowledge",
    "操作指南": "product_knowledge",
}


class KnowledgeService:
    """知识库管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.parser = get_document_parser()
        self.embedding_tool = get_embedding_tool()
        self.milvus_tool = get_milvus_tool()
        self.minio_tool = get_minio_tool()

    async def ingest_document(
        self,
        file_path: str,
        knowledge_type: str,
        title: Optional[str] = None,
    ) -> dict:
        """
        文档入库完整流程：解析 → 分块 → Embedding → Milvus 入库 → MySQL 元数据

        Args:
            file_path: 本地文件路径
            knowledge_type: 知识类型（FAQ / 产品说明 / 政策法规 / 操作指南）
            title: 文档标题，默认使用文件名
        Returns:
            {"knowledge_id": int, "title": str, "chunk_count": int}
        """
        path = Path(file_path)
        if title is None:
            title = path.stem

        # 确定 Milvus 集合
        collection_name = KNOWLEDGE_TYPE_TO_COLLECTION.get(knowledge_type, "product_knowledge")

        # 确保集合存在
        from app.tool.milvus_tool import COLLECTION_CONFIGS
        config = COLLECTION_CONFIGS.get(collection_name, {})
        index_type = config.get("index_type", "IVF_FLAT")
        self.milvus_tool.ensure_collection(collection_name, index_type=index_type)

        # 1. 解析文档
        text = self.parser.parse(file_path)
        logger.info(f"文档解析完成 | file={path.name} | length={len(text)}")

        # 2. 文本分块
        base_metadata = {"source": path.name, "title": title}
        chunks = self.parser.chunk_text(text, chunk_size=512, overlap=64, metadata=base_metadata)

        if not chunks:
            logger.warning(f"文档分块为空 | file={path.name}")
            return {"knowledge_id": 0, "title": title, "chunk_count": 0}

        # 3. 上传原文件到 MinIO（可选，失败不阻塞入库）
        minio_path = None
        try:
            minio_path = self.minio_tool.upload_file(file_path)
        except Exception as e:
            logger.warning(f"MinIO 上传失败（跳过）: {e}")

        # 4. 创建 MySQL 元数据记录
        meta = FinKnowledgeMeta(
            knowledge_type=knowledge_type,
            title=title,
            source_file=path.name,
            minio_path=minio_path,
            milvus_collection=collection_name,
            status="有效",
        )
        self.db.add(meta)
        await self.db.flush()  # 获取自增 ID
        knowledge_id = meta.id

        # 5. 生成 Embedding
        contents = [chunk["content"] for chunk in chunks]
        embeddings = await self.embedding_tool.encode_batch(contents)

        # 6. 为每个 chunk 的 metadata 添加 source_id
        metadatas = []
        for chunk in chunks:
            chunk_meta = {**chunk["metadata"], "source_id": knowledge_id}
            metadatas.append(chunk_meta)

        # 7. Milvus 入库
        self.milvus_tool.insert(
            collection_name=collection_name,
            embeddings=embeddings,
            contents=contents,
            metadatas=metadatas,
        )

        await self.db.commit()

        logger.info(
            f"文档入库完成 | id={knowledge_id} | title={title} | "
            f"chunks={len(chunks)} | collection={collection_name}"
        )
        return {"knowledge_id": knowledge_id, "title": title, "chunk_count": len(chunks)}

    async def list_knowledge(
        self,
        knowledge_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> list[dict]:
        """查询知识列表"""
        stmt = select(FinKnowledgeMeta)
        if knowledge_type:
            stmt = stmt.where(FinKnowledgeMeta.knowledge_type == knowledge_type)
        if status:
            stmt = stmt.where(FinKnowledgeMeta.status == status)
        stmt = stmt.order_by(FinKnowledgeMeta.create_time.desc())
        stmt = stmt.offset((page - 1) * size).limit(size)

        result = await self.db.execute(stmt)
        items = result.scalars().all()

        return [
            {
                "id": item.id,
                "knowledge_type": item.knowledge_type,
                "title": item.title,
                "source_file": item.source_file,
                "status": item.status,
                "create_time": item.create_time.isoformat() if item.create_time else None,
            }
            for item in items
        ]

    async def count_knowledge(
        self,
        knowledge_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        """统计知识数量"""
        stmt = select(func.count(FinKnowledgeMeta.id))
        if knowledge_type:
            stmt = stmt.where(FinKnowledgeMeta.knowledge_type == knowledge_type)
        if status:
            stmt = stmt.where(FinKnowledgeMeta.status == status)
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def delete_knowledge(self, knowledge_id: int) -> bool:
        """
        删除知识（MySQL 元数据 + Milvus 向量 + MinIO 文件）

        Args:
            knowledge_id: 知识 ID
        Returns:
            是否删除成功
        """
        # 1. 查询元数据
        stmt = select(FinKnowledgeMeta).where(FinKnowledgeMeta.id == knowledge_id)
        result = await self.db.execute(stmt)
        meta = result.scalar_one_or_none()

        if not meta:
            logger.warning(f"知识不存在 | id={knowledge_id}")
            return False

        # 2. 删除 Milvus 向量
        try:
            collection = meta.milvus_collection
            if collection:
                ids = self.milvus_tool.get_all_ids(
                    collection, filter_expr=f'metadata["source_id"] == {knowledge_id}'
                )
                if ids:
                    self.milvus_tool.delete_by_ids(collection, ids)
                    logger.info(f"Milvus 向量删除 | id={knowledge_id} | count={len(ids)}")
        except Exception as e:
            logger.warning(f"Milvus 删除失败（继续）: {e}")

        # 3. 删除 MinIO 文件
        try:
            if meta.minio_path:
                self.minio_tool.delete_file(meta.minio_path)
        except Exception as e:
            logger.warning(f"MinIO 删除失败（继续）: {e}")

        # 4. 标记 MySQL 记录为过期
        meta.status = "过期"
        await self.db.commit()

        logger.info(f"知识删除完成 | id={knowledge_id} | title={meta.title}")
        return True

    async def search_knowledge(
        self,
        query: str,
        knowledge_type: Optional[str] = None,
        top_k: int = 5,
    ) -> list[dict]:
        """
        独立知识检索

        Args:
            query: 查询文本
            knowledge_type: 知识类型（可选，不指定则搜索所有集合）
            top_k: 返回 Top K 条
        Returns:
            检索结果列表
        """
        # 确定要搜索的集合
        if knowledge_type:
            collections = [KNOWLEDGE_TYPE_TO_COLLECTION.get(knowledge_type, "product_knowledge")]
        else:
            collections = ["faq_knowledge", "product_knowledge", "policy_knowledge"]

        # 生成查询向量
        query_embedding = await self.embedding_tool.encode(query)

        # 搜索所有相关集合
        all_results = []
        for collection in collections:
            try:
                results = self.milvus_tool.search(
                    collection_name=collection,
                    query_vector=query_embedding,
                    top_k=top_k,
                    output_fields=["content", "metadata"],
                )
                for r in results:
                    r["knowledge_collection"] = collection
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"集合 {collection} 检索失败: {e}")

        # 按 score 排序取 Top K
        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return all_results[:top_k]


def get_knowledge_service(db: AsyncSession) -> KnowledgeService:
    """获取知识库服务实例"""
    return KnowledgeService(db)
