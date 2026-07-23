"""GraphRAG Tool — 将 GraphRAG Pipeline 包装为 LangChain 可调用工具"""

from langchain_core.tools import tool
from app.tool.graphrag_pipeline import GraphRAGPipeline

# 模块级单例：避免每次工具调用都新建 Pipeline（含 Neo4j 连接初始化开销）
_pipeline_instance = None


def _get_pipeline():
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = GraphRAGPipeline()
    return _pipeline_instance


@tool
async def graphrag_tool(query: str) -> str:
    """
    知识图谱检索工具。当用户需要：
    - 查询某个行业有哪些客户或产品
    - 了解客户之间的关联关系
    - 查询特定风险等级的客户/产品分布
    - 获取产品所属行业、关联风险等级等图关系信息
    时，调用此工具检索 Neo4j 知识图谱和 Milvus 文档库。

    Args:
        query: 用户的自然语言查询，如 "查询持有新能源行业产品的所有C4级客户"

    Returns:
        LLM 生成的回答文本（Markdown 格式），包含图谱查询结果和相关文档片段
    """
    pipeline = _get_pipeline()
    result = await pipeline.retrieve(query)
    return result
