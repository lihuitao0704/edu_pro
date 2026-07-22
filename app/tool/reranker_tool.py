"""
Reranker Tool — 基于 LLM 的检索结果重排序
用 LLM 对候选文档按与查询的相关性打分，替代独立 Reranker 模型
"""

import json
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
- 重点考虑：语义匹配度、信息完整度、是否直接回答问题

## 输出格式（严格 JSON）：
[{{"index": 0, "score": 0.95}}, {{"index": 1, "score": 0.3}}, ...]

请仅输出 JSON 数组，不要输出其他内容。"""


class RerankerTool:
    """基于 LLM 的 Reranker"""

    def __init__(self):
        self.llm = get_llm_tool()

    async def rerank(
        self,
        query: str,
        documents: list[dict],
        top_n: int = 5,
    ) -> list[dict]:
        """
        对检索结果进行重排序

        Args:
            query: 用户查询
            documents: 检索结果列表，每项需包含 content 字段
            top_n: 重排后保留的 Top N 条
        Returns:
            重排后的文档列表（带 score 字段，按分数降序）
        """
        if not documents:
            return []

        # 只有1条时直接返回
        if len(documents) == 1:
            return documents[:top_n]

        # 构建文档列表文本
        doc_lines = []
        for i, doc in enumerate(documents):
            content = doc.get("content", "")
            # 截断过长内容，避免超出 token 限制
            if len(content) > 300:
                content = content[:300] + "..."
            doc_lines.append(f"[片段{i}] {content}")

        documents_text = "\n\n".join(doc_lines)
        prompt = RERANK_PROMPT_TEMPLATE.format(query=query, documents=documents_text)

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=512,
            )

            # 解析 LLM 返回的 JSON 评分
            scores = self._parse_scores(response, len(documents))

            # 将评分合并到原始文档
            for item in scores:
                idx = item["index"]
                if 0 <= idx < len(documents):
                    documents[idx]["rerank_score"] = item["score"]

            # 按 rerank_score 降序排序
            documents.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)

            # 用 rerank_score 覆盖原始 score
            for doc in documents:
                if "rerank_score" in doc:
                    doc["score"] = doc["rerank_score"]

            result = documents[:top_n]
            logger.info(
                f"Reranker 完成 | query={query[:30]}... | "
                f"输入={len(documents)} | 输出={len(result)} | "
                f"top_score={result[0].get('score', 0):.3f}" if result else "无结果"
            )
            return result

        except Exception as e:
            logger.warning(f"LLM Reranker 失败，跳过重排序: {e}")
            # 降级：直接返回原始排序结果
            return documents[:top_n]

    def _parse_scores(self, response: str, doc_count: int) -> list[dict]:
        """解析 LLM 返回的评分 JSON"""
        try:
            # 尝试提取 JSON 数组
            text = response.strip()
            # 处理可能被 markdown 包裹的情况
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            scores = json.loads(text)
            if isinstance(scores, list):
                return scores

        except (json.JSONDecodeError, IndexError, KeyError) as e:
            logger.warning(f"Reranker 评分解析失败: {e}，原始响应: {response[:200]}")

        # 解析失败时给所有文档相同分数（保持原序）
        return [{"index": i, "score": 0.5} for i in range(doc_count)]


# 全局单例
_reranker_tool: Optional[RerankerTool] = None


def get_reranker_tool() -> RerankerTool:
    """获取 Reranker 工具单例"""
    global _reranker_tool
    if _reranker_tool is None:
        _reranker_tool = RerankerTool()
    return _reranker_tool
