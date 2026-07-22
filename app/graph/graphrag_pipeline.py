"""GraphRAG 融合检索 Pipeline"""

from typing import List
from app.config.settings import get_settings

settings = get_settings()


class GraphRAGPipeline:
    """
    GraphRAG 融合检索
    将 Milvus 向量检索结果与 Neo4j 图谱查询结果融合排序
    """

    def __init__(self):
        self.vector_weight = settings.graphrag.vector_weight
        self.graph_weight = settings.graphrag.graph_weight

    async def retrieve(
        self,
        query: str,
        vector_results: List[dict] = None,
        graph_results: List[dict] = None,
    ) -> List[dict]:
        """融合检索"""
        vector_results = vector_results or []
        graph_results = graph_results or []

        merged = {}

        # 向量结果：用 "v:" 前缀避免与图谱结果 key 碰撞
        for item in vector_results:
            raw_key = item.get("id") or item.get("content", "")[:50]
            key = f"v:{raw_key}"
            merged[key] = {
                "content": item.get("content", ""),
                "vector_score": item.get("score", 0),
                "graph_score": 0,
                "source": "vector",
            }

        # 图谱结果：无 score 时默认 0（图谱查询为精确匹配，不提供相关性分数时不应虚高）
        for item in graph_results:
            content = str(item)
            raw_key = content[:50]
            # 先尝试与已有向量结果做内容级去重
            dedup_key = f"v:{raw_key}"
            if dedup_key in merged:
                merged[dedup_key]["graph_score"] = item.get("score", 0)
                merged[dedup_key]["source"] = "hybrid"
            else:
                key = f"g:{raw_key}"
                merged[key] = {
                    "content": content,
                    "vector_score": 0,
                    "graph_score": item.get("score", 0),
                    "source": "graph",
                }

        # 计算综合分
        for item in merged.values():
            item["final_score"] = (
                self.vector_weight * item["vector_score"]
                + self.graph_weight * item["graph_score"]
            )

        # 排序
        return sorted(merged.values(), key=lambda x: x["final_score"], reverse=True)
