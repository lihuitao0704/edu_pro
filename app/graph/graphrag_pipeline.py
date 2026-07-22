"""
GraphRAG 融合检索 Pipeline

完整五阶段流程：
  阶段1 — 实体提取（LLM）：从用户自然语言中提取实体（行业、风险等级、产品类型等）
  阶段2 — 并行检索：Neo4j 多跳查询 + Milvus 向量检索
  阶段3 — 融合排序：加权合并，去重，降序
  阶段4 — 格式化上下文：组装为 LLM 可消费的结构化 Context
  阶段5 — 注入 LLM 生成回答

设计原则：
  - Neo4j 多跳查询通过 Neo4jClient 执行，不直接操作 driver
  - Milvus 检索通过 OpenAI Embedding API 编码 query
  - 两路检索并行执行（asyncio.gather），互不阻塞
  - 融合权重可配置（settings.graphrag）
"""

import json
import asyncio
from typing import List, Dict, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.config.settings import get_settings
from app.graph.neo4j_client import Neo4jClient
from app.graph.cypher_templates import (
    CUSTOMERS_BY_INDUSTRY_AND_RISK,
    GRAPH_ENTITY_SEARCH,
    FULL_GRAPH_OVERVIEW,
    PEER_PRODUCTS_BY_INDUSTRY,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

# ═══════════════════════════════════════════════════════════════
# 实体提取 Prompt
# ═══════════════════════════════════════════════════════════════

ENTITY_EXTRACTION_PROMPT = """你是一个金融知识图谱实体提取器。从用户问题中提取以下实体，以 JSON 格式返回。

支持的实体类型：
- industry: 行业名称（如 新能源、消费、医药、科技、金融、地产）
- risk_level: 风险等级，注意用户说的可能是 "C4/进取型" 或 "R4/进取型"，
             统一映射为 RiskLevel 的 level 字段（R1/R2/R3/R4/R5）
             C4→R4, C5→R5, C1→R1, C2→R2, C3→R3
- product_type: 产品类型（如 股票基金、债券基金、混合基金、货币基金）
- customer_name: 客户姓名
- product_name: 产品名称关键词

规则：
1. 只提取问题中明确提到的实体，未提到的字段填 null
2. industry 只取一个最匹配的值
3. risk_level 只返回 R1-R5 格式
4. 返回纯 JSON，不要包含 markdown 代码块标记

示例：
问题："查询持有新能源行业产品的所有C4级进取型客户"
返回：{"industry": "新能源", "risk_level": "R4", "product_type": null, "customer_name": null, "product_name": null}

问题："张三买了哪些科技类的基金"
返回：{"industry": "科技", "risk_level": null, "product_type": "基金", "customer_name": "张三", "product_name": null}
"""

# ═══════════════════════════════════════════════════════════════
# 回答生成 Prompt
# ═══════════════════════════════════════════════════════════════

ANSWER_GENERATION_PROMPT = """你是智能财富管理系统的图数据分析师。根据图谱查询结果和知识库文档，回答用户的问题。

## 回答规则
1. 先给出查询结论（简洁的一句话总结）
2. 如果有图谱数据，用 Markdown 表格展示客户/产品/行业的关联关系
3. 如果有知识库文档片段，引用相关的内容补充说明
4. 如果图谱结果为空，明确告知用户"未找到符合条件的数据"，并说明可能的原因
5. 回答要专业但通俗，面向理财顾问

## 上下文数据

### 图谱查询结果（Neo4j 结构化数据）
{graph_context}

### 知识库文档（Milvus 检索片段）
{vector_context}
"""


class GraphRAGPipeline:
    """
    GraphRAG 融合检索 Pipeline

    用法:
        pipeline = GraphRAGPipeline()
        answer = await pipeline.retrieve("查询持有新能源的C4级客户")
        print(answer)
    """

    def __init__(self):
        self.neo4j = Neo4jClient()
        self.vector_weight = settings.graphrag.vector_weight   # 默认 0.6
        self.graph_weight = settings.graphrag.graph_weight      # 默认 0.4

        # LLM（实体提取 + 回答生成 共用）
        self._llm = ChatOpenAI(
            model=settings.llm.openai_model_chat,
            temperature=0.3,   # 实体提取需要低温度保证稳定
            max_tokens=settings.llm.openai_max_tokens,
            timeout=settings.llm.openai_timeout,
            max_retries=settings.llm.openai_max_retries,
            openai_api_key=settings.llm.openai_api_key,
            openai_api_base=settings.llm.openai_base_url,
        )

        # Embedding 客户端（向量检索用）
        self._embedding_client = None

    # ═══════════════════════════════════════════════════════════
    # 对外主入口
    # ═══════════════════════════════════════════════════════════

    async def retrieve(self, query: str) -> str:
        """
        GraphRAG 完整检索流程

        Args:
            query: 用户自然语言提问

        Returns:
            LLM 生成的最终回答（Markdown 格式）
        """
        logger.info(f"[GraphRAG] 收到查询: {query}")

        # ── 阶段1: 实体提取 ──
        entities = await self._extract_entities(query)
        logger.info(f"[GraphRAG] 实体提取结果: {entities}")

        # ── 阶段2: 并行检索 ──
        graph_task = self._graph_search(entities)
        vector_task = self._vector_search(query)
        graph_results, vector_results = await asyncio.gather(graph_task, vector_task)
        logger.info(
            f"[GraphRAG] 检索完成: 图谱 {len(graph_results)} 条, 向量 {len(vector_results)} 条"
        )

        # ── 阶段3: 融合排序 ──
        fused = self._fusion_rank(graph_results, vector_results)

        # ── 阶段4: 格式化上下文 ──
        graph_ctx = self._format_graph_context(graph_results, entities)
        vector_ctx = self._format_vector_context(fused)

        # ── 阶段5: 注入 LLM 生成回答 ──
        answer = await self._generate_answer(query, graph_ctx, vector_ctx)
        return answer

    async def retrieve_raw(self, query: str) -> dict:
        """
        仅检索不生成回答，返回原始结构化数据（供 Agent Tool 调用）

        Returns:
            {
                "entities": {...},
                "graph_results": [...],
                "vector_results": [...],
                "fused": [...]
            }
        """
        entities = await self._extract_entities(query)
        graph_results, vector_results = await asyncio.gather(
            self._graph_search(entities),
            self._vector_search(query),
        )
        fused = self._fusion_rank(graph_results, vector_results)
        return {
            "entities": entities,
            "graph_results": graph_results,
            "vector_results": vector_results,
            "fused": fused,
        }

    # ═══════════════════════════════════════════════════════════
    # 阶段1: 实体提取
    # ═══════════════════════════════════════════════════════════

    async def _extract_entities(self, query: str) -> dict:
        """用 LLM 从用户提问中提取实体"""
        try:
            response = await self._llm.ainvoke([
                SystemMessage(content=ENTITY_EXTRACTION_PROMPT),
                HumanMessage(content=query),
            ])
            content = response.content.strip()
            # 去除可能的 markdown 代码块标记
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content[:-3]
            return json.loads(content)
        except Exception as e:
            logger.warning(f"[GraphRAG] 实体提取失败: {e}，使用空实体继续")
            return {
                "industry": None,
                "risk_level": None,
                "product_type": None,
                "customer_name": None,
                "product_name": None,
            }

    # ═══════════════════════════════════════════════════════════
    # 阶段2a: Neo4j 多跳查询
    # ═══════════════════════════════════════════════════════════

    async def _graph_search(self, entities: dict) -> List[dict]:
        """根据实体选择 Cypher 模板执行图谱查询"""
        results = []
        industry = entities.get("industry")
        risk_level = entities.get("risk_level")
        customer_name = entities.get("customer_name")
        customer_id = entities.get("customer_id")

        # ── 路径1: 行业 + 风险等级 → 客户列表（核心多跳） ──
        if industry or risk_level:
            try:
                params = {
                    "industry": industry or "",
                    "risk_level": risk_level or "",
                }
                data = await self.neo4j.run_query(
                    CUSTOMERS_BY_INDUSTRY_AND_RISK, params
                )
                for row in data:
                    results.append({
                        "type": "customer_industry",
                        "customer_id": row.get("customer_id"),
                        "customer_name": row.get("customer_name"),
                        "customer_level": row.get("customer_level"),
                        "risk_level": row.get("risk_level"),
                        "risk_description": row.get("risk_description"),
                        "industry": row.get("industry_name"),
                        "holdings": row.get("holdings", []),
                        "graph_score": 0.9,  # 精确匹配给高分
                        "source": "graph",
                    })
            except Exception as e:
                logger.error(f"[GraphRAG] 多跳查询失败: {e}")

        # ── 路径2: 实体模糊搜索（兜底） ──
        keywords = [v for v in [industry, customer_name, entities.get("product_name")]
                    if v]
        if keywords and not results:
            for kw in keywords:
                try:
                    data = await self.neo4j.run_query(
                        GRAPH_ENTITY_SEARCH, {"keyword": kw}
                    )
                    for row in data:
                        results.append({
                            "type": "entity_match",
                            "labels": row.get("labels", []),
                            "name": row.get("name"),
                            "level": row.get("level"),
                            "description": row.get("description"),
                            "graph_score": 0.6,
                            "source": "graph",
                        })
                except Exception as e:
                    logger.warning(f"[GraphRAG] 实体搜索 '{kw}' 失败: {e}")

        return results

    # ═══════════════════════════════════════════════════════════
    # 阶段2b: Milvus 向量检索
    # ═══════════════════════════════════════════════════════════

    async def _vector_search(self, query: str) -> List[dict]:
        """Milvus 向量相似度检索"""
        try:
            embedding = await self._get_embedding(query)
            if embedding is None:
                return []
            return await self._search_milvus(embedding)
        except Exception as e:
            logger.warning(f"[GraphRAG] 向量检索失败: {e}")
            return []

    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        """
        调用 Embedding API 编码文本。

        优先使用 OpenAI 兼容接口（settings.llm），
        如果失败且配置了 Ollama，则降级到 Ollama。
        """
        if self._embedding_client is None:
            from openai import AsyncOpenAI
            self._embedding_client = AsyncOpenAI(
                api_key=settings.llm.openai_api_key,
                base_url=settings.llm.openai_base_url,
                timeout=settings.llm.openai_timeout,
                max_retries=settings.llm.openai_max_retries,
            )
        try:
            resp = await self._embedding_client.embeddings.create(
                model=settings.llm.openai_model_embedding,
                input=text,
            )
            return resp.data[0].embedding
        except Exception as e:
            logger.warning(f"[GraphRAG] OpenAI Embedding 失败: {e}，尝试 Ollama 降级")
            return await self._get_embedding_ollama(text)

    async def _get_embedding_ollama(self, text: str) -> Optional[List[float]]:
        """Ollama 本地 Embedding 降级方案"""
        import httpx
        try:
            ollama_url = getattr(settings.llm, "ollama_embed_url", None)
            if not ollama_url:
                # 尝试从环境变量直接读取
                import os
                ollama_url = os.getenv("OLLAMA_EMBED_URL", "http://192.168.110.59:11434")

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{ollama_url}/api/embeddings",
                    json={
                        "model": settings.llm.openai_model_embedding,
                        "prompt": text,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("embedding", [])
                else:
                    logger.warning(f"[GraphRAG] Ollama Embedding 失败: HTTP {resp.status_code}")
                    return None
        except Exception as e:
            logger.warning(f"[GraphRAG] Ollama Embedding 失败: {e}")
            return None

    async def _search_milvus(self, embedding: List[float]) -> List[dict]:
        """
        在 Milvus 中执行向量检索。

        遍历所有有数据的 collection，使用 MilvusClient（新版 API）搜索。
        实际 collection 的向量字段名为 `dense_vector` 或 `embedding`，自动适配。
        """
        try:
            from pymilvus import MilvusClient
            from app.config.database import init_milvus
            init_milvus()

            client = MilvusClient(
                uri=f"http://{settings.milvus.host}:{settings.milvus.port}",
                timeout=getattr(settings.milvus, "timeout", 5),
            )

            results = []
            # 遍历所有有数据的 collection（已确认：doc_chunks, file_chunks,
            # conversations, qa_pairs 有数据；faq/product/policy_knowledge 为空）
            for coll_name in [
                "doc_chunks", "file_chunks", "conversations", "qa_pairs",
                "faq_knowledge", "product_knowledge", "policy_knowledge",
            ]:
                try:
                    # 检测该 collection 的向量字段名
                    coll_info = client.describe_collection(coll_name)
                    vector_field = None
                    output_fields = []
                    for field in coll_info.get("fields", []):
                        if field.get("type") in (101, 104, "FLOAT_VECTOR", "SPARSE_FLOAT_VECTOR"):
                            # 优先用 DENSE 向量字段（type=101 即 FLOAT_VECTOR）
                            if field.get("type") == 101 or field.get("type") == "FLOAT_VECTOR":
                                vector_field = field.get("name")
                        else:
                            # 非向量字段都作为 output
                            output_fields.append(field.get("name"))

                    if not vector_field:
                        continue  # 没有向量字段，跳过

                    # 限制 output_fields 最多 5 个
                    output_fields = output_fields[:5]

                    resp = client.search(
                        collection_name=coll_name,
                        data=[embedding],
                        anns_field=vector_field,
                        limit=settings.milvus.top_k,
                        output_fields=output_fields,
                    )

                    for hits in resp:
                        for hit in hits:
                            if hit.get("distance", 0) >= settings.milvus.score_threshold:
                                entity = hit.get("entity", {})
                                results.append({
                                    "content": entity.get("content") or entity.get("chunk_text") or entity.get("answer", ""),
                                    "title": entity.get("file_name") or entity.get("doc_id") or entity.get("question", ""),
                                    "source": coll_name,
                                    "vector_score": float(hit.get("distance", 0)),
                                    "collection": coll_name,
                                })
                except Exception:
                    pass  # collection 不存在或加载失败则跳过

            return results
        except Exception as e:
            logger.warning(f"[GraphRAG] Milvus 检索异常: {e}")
            return []

    # ═══════════════════════════════════════════════════════════
    # 阶段3: 融合排序
    # ═══════════════════════════════════════════════════════════

    def _fusion_rank(
        self,
        graph_results: List[dict],
        vector_results: List[dict],
    ) -> List[dict]:
        """
        加权融合排序

        - 图谱结果以 graph_score（0-1）参与
        - 向量结果以 vector_score（0-1，已归一化）参与
        - 综合分 = graph_weight × graph_score + vector_weight × vector_score
        """
        merged = []

        # 图谱结果：graph_score 已是结构化精确度
        for item in graph_results:
            merged.append({
                "content": json.dumps(item, ensure_ascii=False, default=str),
                "graph_score": item.get("graph_score", 0.5),
                "vector_score": 0,
                "final_score": self.graph_weight * item.get("graph_score", 0.5),
                "source": "graph",
                "type": item.get("type", ""),
            })

        # 向量结果
        for item in vector_results:
            vs = item.get("vector_score", 0)
            merged.append({
                "content": item.get("content", ""),
                "title": item.get("title", ""),
                "graph_score": 0,
                "vector_score": vs,
                "final_score": self.vector_weight * vs,
                "source": "vector",
                "collection": item.get("collection", ""),
            })

        # 综合分重新计算（考虑双向加成）
        for item in merged:
            if item["source"] == "graph":
                item["final_score"] = self.graph_weight * item["graph_score"]
            else:
                item["final_score"] = self.vector_weight * item["vector_score"]

        merged.sort(key=lambda x: x["final_score"], reverse=True)
        return merged

    # ═══════════════════════════════════════════════════════════
    # 阶段4: 格式化上下文
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _format_graph_context(graph_results: List[dict], entities: dict) -> str:
        """将图谱结果格式化为 LLM 可读的 Markdown 段落"""
        if not graph_results:
            # 尝试显示搜索条件
            active_filters = {k: v for k, v in entities.items() if v}
            if active_filters:
                return f"图谱查询未返回结果。查询条件：{json.dumps(active_filters, ensure_ascii=False)}"
            return "图谱查询未返回结果。"

        lines = []
        for i, item in enumerate(graph_results, 1):
            rtype = item.get("type", "")
            if rtype == "customer_industry":
                lines.append(f"**结果 {i}：客户画像匹配**")
                lines.append(f"- 客户ID: {item.get('customer_id')}")
                lines.append(f"- 姓名: {item.get('customer_name')}")
                lines.append(f"- 客户等级: {item.get('customer_level')}")
                lines.append(f"- 风险等级: {item.get('risk_level')} ({item.get('risk_description')})")
                lines.append(f"- 关联行业: {item.get('industry')}")
                holdings = item.get("holdings", [])
                if holdings:
                    lines.append("- 持仓产品:")
                    for h in holdings:
                        lines.append(f"  - {h.get('name')} ({h.get('type')}, {h.get('risk')})")
                lines.append("")
            elif rtype == "entity_match":
                lines.append(f"**结果 {i}：实体匹配**")
                lines.append(f"- 类型: {item.get('labels')}")
                lines.append(f"- 名称: {item.get('name')}")
                if item.get("description"):
                    lines.append(f"- 描述: {item.get('description')}")
                lines.append("")
            else:
                lines.append(f"**结果 {i}**")
                lines.append(json.dumps(item, ensure_ascii=False, default=str))
                lines.append("")

        return "\n".join(lines) if lines else "无图谱查询结果"

    @staticmethod
    def _format_vector_context(fused: List[dict]) -> str:
        """将融合后的向量结果格式化为 LLM 可读的段落"""
        vector_items = [f for f in fused if f["source"] == "vector"]
        if not vector_items:
            return "未检索到相关文档片段。"

        lines = []
        for i, item in enumerate(vector_items[:5], 1):  # 最多 5 条
            title = item.get("title", "无标题")
            content = item.get("content", "")
            score = item.get("vector_score", 0)
            lines.append(f"**片段 {i}** [{title}] (相关度: {score:.2f})")
            lines.append(f"> {content[:500]}")  # 截断过长内容
            lines.append("")

        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════
    # 阶段5: 注入 LLM 生成回答
    # ═══════════════════════════════════════════════════════════

    async def _generate_answer(
        self, query: str, graph_ctx: str, vector_ctx: str
    ) -> str:
        """将图谱+向量上下文注入 LLM，生成最终回答"""
        system_prompt = ANSWER_GENERATION_PROMPT.format(
            graph_context=graph_ctx or "无",
            vector_context=vector_ctx or "无",
        )

        # 如果两路都没有结果
        if not graph_ctx and not vector_ctx:
            return (
                "抱歉，未能在知识图谱和文档库中找到与您问题相关的信息。\n\n"
                f"您的问题是：「{query}」\n\n"
                "建议：\n"
                "- 确认客户ID、行业名称、风险等级是否正确\n"
                "- 尝试使用更通用的关键词搜索"
            )

        try:
            response = await self._llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=query),
            ])
            return response.content
        except Exception as e:
            logger.error(f"[GraphRAG] LLM 调用失败: {e}")
            # 兜底：返回原始检索结果
            fallback = f"## 查询结果\n\n### 图谱数据\n{graph_ctx}\n\n### 相关文档\n{vector_ctx}"
            return fallback

    # ═══════════════════════════════════════════════════════════
    # 辅助查询方法（供外部直接调用）
    # ═══════════════════════════════════════════════════════════

    async def get_full_overview(self) -> List[dict]:
        """获取全图谱概览"""
        return await self.neo4j.run_query(FULL_GRAPH_OVERVIEW)

    async def get_peer_products(self, customer_id: str) -> List[dict]:
        """获取某客户同行业其他在售产品"""
        return await self.neo4j.run_query(
            PEER_PRODUCTS_BY_INDUSTRY, {"customer_id": customer_id}
        )
