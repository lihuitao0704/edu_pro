"""
Reranker Tool — LLM + Milvus 混合检索重排序
LLM 对候选文档按与查询的相关性打分，与 Milvus 向量分数加权融合
"""

import json
import re
from typing import Optional

from app.tool.llm_tool import get_llm_tool
from app.utils.logger import get_logger

logger = get_logger("tool.reranker")

# LLM Reranker Prompt 模板
RERANK_PROMPT_TEMPLATE = """你是一个金融知识检索结果评估专家。请对以下检索片段与用户问题的相关性进行打分。

## 用户问题：
{query}

## 检索片段列表：
{documents}

## 评分规则：
- 对每个片段打一个 0.0 到 1.0 之间的相关性分数
- 1.0 表示完全相关，0.0 表示完全不相关
- 重点考虑：
  1. 直接回答问题的程度
  2. 金融概念的相关性（如"资管新规"与"销售管理办法"、"适当性管理"、"反洗钱"都密切相关）
  3. 法规政策的关联性（同一监管框架下的不同文件通常相关）

## 输出格式（严格 JSON 数组，不要输出任何其他内容）：
[{{"index": 0, "score": 0.95}}, {{"index": 1, "score": 0.3}}, ...]

仅输出 JSON 数组，不要输出任何解释、前言、markdown 或代码块。"""

# 混合检索权重配置
LLM_RERANK_WEIGHT = 0.55    # LLM 语义相关性
MILVUS_VECTOR_WEIGHT = 0.45  # Milvus 向量相似度


class RerankerTool:
    """LLM + Milvus 混合 Reranker"""

    def __init__(self):
        self.llm = get_llm_tool()

    async def rerank(
        self,
        query: str,
        documents: list[dict],
        top_n: int = 5,
    ) -> list[dict]:
        """
        LLM + Milvus 混合重排序

        流程：
        1. 调用 LLM 对候选文档打分（语义相关性）
        2. 将 LLM 分数与 Milvus 向量相似度分数加权融合
        3. 按融合分数排序，返回 top_n

        Args:
            query: 用户查询
            documents: 检索结果列表，每项需包含 content 和 score(Milvus分数) 字段
            top_n: 重排后保留的 Top N 条
        Returns:
            重排后的文档列表（带 score/final_score 字段，按融合分数降序）
        """
        if not documents:
            return []

        # 如果只有1条，直接返回
        if len(documents) == 1:
            documents[0]["final_score"] = documents[0].get("score", 0)
            return documents

        # 1. 构建文档列表文本
        doc_texts = []
        for i, doc in enumerate(documents):
            content = doc.get("content", "")
            # 截断过长内容，避免 token 超限
            if len(content) > 500:
                content = content[:500] + "..."
            doc_texts.append(f"[片段{i}] {content}")
        documents_text = "\n".join(doc_texts)

        # 2. 调用 LLM 打分
        prompt = RERANK_PROMPT_TEMPLATE.format(
            query=query,
            documents=documents_text,
        )
        messages = [{"role": "user", "content": prompt}]

        try:
            llm_response = await self.llm.chat(messages=messages, temperature=0.1, max_tokens=512)
            llm_scores = self._parse_scores(llm_response, len(documents))
            logger.info(f"LLM Reranker 调用成功 | 解析到 {len(llm_scores)} 个评分")
        except Exception as e:
            logger.warning(f"LLM Reranker 调用失败，降级为 Milvus 向量直排: {e}")
            # 降级：直接用 Milvus 分数排序
            documents.sort(key=lambda x: x.get("score", 0), reverse=True)
            for doc in documents[:top_n]:
                doc["final_score"] = doc.get("score", 0)
            return documents[:top_n]

        # 3. 构建 LLM 分数映射（index -> score）
        llm_score_map = {}
        for item in llm_scores:
            idx = item.get("index")
            score = item.get("score", 0)
            if idx is not None and 0 <= idx < len(documents):
                llm_score_map[idx] = score

        # 4. 归一化 Milvus 分数到 [0, 1]
        milvus_scores = [doc.get("score", 0) for doc in documents]
        max_milvus = max(milvus_scores) if milvus_scores else 1.0
        min_milvus = min(milvus_scores) if milvus_scores else 0.0
        milvus_range = max_milvus - min_milvus if max_milvus != min_milvus else 1.0

        # 5. 加权融合
        for i, doc in enumerate(documents):
            milvus_norm = (doc.get("score", 0) - min_milvus) / milvus_range
            llm_score = llm_score_map.get(i, 0.0)
            # 加权融合
            final_score = LLM_RERANK_WEIGHT * llm_score + MILVUS_VECTOR_WEIGHT * milvus_norm
            doc["final_score"] = round(final_score, 4)
            doc["llm_score"] = round(llm_score, 4)
            doc["milvus_score"] = round(doc.get("score", 0), 4)

        # 6. 按融合分数降序排序
        documents.sort(key=lambda x: x.get("final_score", 0), reverse=True)

        result = documents[:top_n]

        if result:
            logger.info(
                f"混合 Reranker 完成 | query={query[:30]}... | "
                f"输入={len(documents)} → 输出={len(result)} | "
                f"top_final={result[0].get('final_score', 0):.4f} "
                f"(llm={result[0].get('llm_score', 0):.3f}, milvus={result[0].get('milvus_score', 0):.3f})"
            )
        return result

    def _parse_scores(self, response: str, doc_count: int) -> list[dict]:
        """解析 LLM 返回的评分 JSON，多重容错"""
        try:
            text = response.strip()

            if not text:
                logger.warning("Reranker LLM 返回空响应，使用默认分数")
                return [{"index": i, "score": 0.5} for i in range(doc_count)]

            # 1. 去除可能的 markdown 代码块包裹
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            text = text.strip()

            # 2. 尝试直接解析
            if text.startswith("["):
                scores = json.loads(text)
                if isinstance(scores, list):
                    return scores

            # 3. 从文本中提取 JSON 数组
            json_match = re.search(r'\[[\s\S]*\]', text)
            if json_match:
                try:
                    scores = json.loads(json_match.group())
                    if isinstance(scores, list):
                        return scores
                except json.JSONDecodeError:
                    pass

            # 4. 提取所有 {"index": N, "score": N.N} 格式
            pattern = r'\{[^{}]*"index"\s*:\s*(\d+)[^{}]*"score"\s*:\s*([\d.]+)[^{}]*\}'
            matches = re.findall(pattern, text)
            if matches:
                return [{"index": int(idx), "score": float(score)} for idx, score in matches]

            logger.warning(f"Reranker 解析失败，使用默认分数 0.5 | response={text[:200]}")

        except Exception as e:
            logger.warning(f"Reranker 评分解析异常: {e}")

        return [{"index": i, "score": 0.5} for i in range(doc_count)]


# 全局单例
_reranker_tool: Optional[RerankerTool] = None


def get_reranker_tool() -> RerankerTool:
    """获取 Reranker 工具单例"""
    global _reranker_tool
    if _reranker_tool is None:
        _reranker_tool = RerankerTool()
    return _reranker_tool
