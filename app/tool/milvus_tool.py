"""
Milvus Tool — 向量数据库操作
封装 Milvus 集合管理、向量插入、检索、删除
"""

from typing import Optional
from pymilvus import (
    Collection,
    CollectionSchema,
    FieldSchema,
    DataType,
    utility,
    connections,
)

from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger("tool.milvus")
settings = get_settings()

# 集合配置（复用 .env）
COLLECTION_CONFIGS = {
    "faq_knowledge": {
        "index_type": "HNSW",
        "metric_type": "COSINE",
        "top_k": 5,
        "threshold": 0.75,
    },
    "product_knowledge": {
        "index_type": "IVF_FLAT",
        "metric_type": "COSINE",
        "top_k": 10,
        "threshold": 0.7,
    },
    "policy_knowledge": {
        "index_type": "IVF_FLAT",
        "metric_type": "COSINE",
        "top_k": 10,
        "threshold": 0.7,
    },
}


class MilvusTool:
    """Milvus 向量数据库工具"""

    def __init__(self):
        self.dim = settings.milvus.dim  # 1536

    def ensure_collection(self, collection_name: str, index_type: str = "IVF_FLAT"):
        """
        确保集合存在，不存在则创建

        Args:
            collection_name: 集合名称
            index_type: 索引类型（HNSW / IVF_FLAT）
        """
        if utility.has_collection(collection_name):
            logger.info(f"集合已存在: {collection_name}")
            return

        # 定义 Schema
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=8192),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.dim),
            FieldSchema(name="metadata", dtype=DataType.JSON),
        ]
        schema = CollectionSchema(fields=fields, description=f"{collection_name} 知识库")

        # 创建集合
        collection = Collection(name=collection_name, schema=schema)
        logger.info(f"集合创建成功: {collection_name}")

        # 创建索引
        index_params = {
            "index_type": index_type,
            "metric_type": "COSINE",
            "params": {"M": 16, "efConstruction": 200} if index_type == "HNSW" else {"nlist": 128},
        }
        collection.create_index(field_name="embedding", index_params=index_params)
        logger.info(f"索引创建成功: {collection_name} ({index_type})")

    def insert(
        self,
        collection_name: str,
        embeddings: list[list[float]],
        contents: list[str],
        metadatas: list[dict],
    ):
        """
        批量插入向量

        Args:
            collection_name: 集合名称
            embeddings: 向量列表
            contents: 文本内容列表
            metadatas: 元数据列表
        """
        collection = Collection(collection_name)
        data = [contents, embeddings, metadatas]
        result = collection.insert(data)
        collection.flush()
        logger.info(f"向量插入成功 | collection={collection_name} | count={len(embeddings)}")
        return result

    def search(
        self,
        collection_name: str,
        query_vector: list[float],
        top_k: int = 10,
        output_fields: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        向量检索

        Args:
            collection_name: 集合名称
            query_vector: 查询向量
            top_k: 返回 Top K 条
            output_fields: 需要返回的字段
        Returns:
            检索结果列表，每项包含 content, metadata, score
        """
        output_fields = output_fields or ["content", "metadata"]
        collection = Collection(collection_name)
        collection.load()

        search_params = {
            "metric_type": "COSINE",
            "params": {"ef": 64} if COLLECTION_CONFIGS.get(collection_name, {}).get("index_type") == "HNSW" else {"nprobe": 16},
        }

        results = collection.search(
            data=[query_vector],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            output_fields=output_fields,
        )

        # 格式化结果
        hits = []
        for hits_batch in results:
            for hit in hits_batch:
                hits.append({
                    "content": hit.entity.get("content"),
                    "metadata": hit.entity.get("metadata"),
                    "score": hit.score,
                })

        logger.info(f"向量检索完成 | collection={collection_name} | top_k={top_k} | hits={len(hits)}")
        return hits

    def delete_by_ids(self, collection_name: str, ids: list[int]):
        """
        按 ID 删除向量

        Args:
            collection_name: 集合名称
            ids: 主键 ID 列表
        """
        collection = Collection(collection_name)
        expr = f"id in {ids}"
        result = collection.delete(expr)
        collection.flush()
        logger.info(f"向量删除成功 | collection={collection_name} | count={len(ids)}")
        return result

    def get_all_ids(self, collection_name: str, filter_expr: Optional[str] = None) -> list[int]:
        """
        获取所有 ID（用于删除文档时清理）

        Args:
            collection_name: 集合名称
            filter_expr: 过滤表达式（如 'metadata["source_id"] == 123'）
        Returns:
            ID 列表
        """
        collection = Collection(collection_name)
        collection.load()

        if filter_expr:
            results = collection.query(expr=filter_expr, output_fields=["id"])
        else:
            results = collection.query(expr="id >= 0", output_fields=["id"])

        ids = [r["id"] for r in results]
        logger.info(f"获取 ID 完成 | collection={collection_name} | count={len(ids)}")
        return ids

    def get_collection_config(self, collection_name: str) -> dict:
        """获取集合配置（top_k, threshold 等）"""
        return COLLECTION_CONFIGS.get(collection_name, {"top_k": 10, "threshold": 0.7})


# 全局单例
_milvus_tool: Optional[MilvusTool] = None


def get_milvus_tool() -> MilvusTool:
    """获取 Milvus 工具单例"""
    global _milvus_tool
    if _milvus_tool is None:
        _milvus_tool = MilvusTool()
    return _milvus_tool
