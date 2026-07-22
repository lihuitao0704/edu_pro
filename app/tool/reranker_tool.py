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

        策略：跳过 LLM Reranker（推理模型无法稳定输出 JSON），
        直接使用 Milvus 向量相似度分数排序。

        Args:
            query: 用户查询
            documents: 检索结果列表，每项需包含 content 字段
            top_n: 重排后保留的 Top N 条
        Returns:
            重排后的文档列表（带 score 字段，按分数降序）
        """
        if not documents:
            return []

        # 直接使用 Milvus 向量相似度分数排序（已在 search 阶段计算好）
        # documents 中的 score 字段就是 Milvus 的 cosine similarity
        documents.sort(key=lambda x: x.get("score", 0), reverse=True)

        result = documents[:top_n]
        logger.info(
            f"Reranker 完成（向量分数直排） | query={query[:30]}... | "
            f"输入={len(documents)} | 输出={len(result)} | "
            f"top_score={result[0].get('score', 0):.3f}" if result else "无结果"
        )
        return result

    def _parse_scores(self, response: str, doc_count: int) -> list[dict]:
        """解析 LLM 返回的评分 JSON"""
        import re
        try:
            # 尝试提取 JSON 数组
            text = response.strip()

            # 调试日志 - 打印完整响应
            logger.info(f"Reranker 原始响应长度: {len(text)}")
            logger.info(f"Reranker 原始响应: {text[:1000]}")

            # 如果响应为空，直接返回默认分数
            if not text:
                logger.warning("Reranker LLM返回空响应，使用默认分数")
                return [{"index": i, "score": 0.5} for i in range(doc_count)]

            # 1. 先尝试直接解析
            if text.startswith("["):
                scores = json.loads(text)
                if isinstance(scores, list):
                    logger.info(f"Reranker 解析成功（直接解析）: {len(scores)} 个评分")
                    return scores

            # 2. 尝试从 markdown 代码块中提取
            if "```" in text:
                code_blocks = re.findall(r'```(?:json)?\s*(\[.*?\])\s*```', text, re.DOTALL)
                for block in code_blocks:
                    try:
                        scores = json.loads(block)
                        if isinstance(scores, list):
                            logger.info(f"Reranker 解析成功（markdown代码块）: {len(scores)} 个评分")
                            return scores
                    except json.JSONDecodeError:
                        continue

            # 3. 尝试从文本中提取 JSON 数组（可能被推理文本包裹）
            json_match = re.search(r'\[[\s\S]*?\{[\s\S]*?"index"[\s\S]*?"score"[\s\S]*?\}[\s\S]*?\]', text)
            if json_match:
                try:
                    scores = json.loads(json_match.group())
                    if isinstance(scores, list):
                        logger.info(f"Reranker 解析成功（正则提取）: {len(scores)} 个评分")
                        return scores
                except json.JSONDecodeError:
                    pass

            # 4. 尝试提取所有 {"index": N, "score": N.N} 格式的片段
            pattern = r'\{[^{}]*"index"\s*:\s*(\d+)[^{}]*"score"\s*:\s*([\d.]+)[^{}]*\}'
            matches = re.findall(pattern, text)
            if matches:
                scores = [{"index": int(idx), "score": float(score)} for idx, score in matches]
                logger.info(f"Reranker 解析成功（模式匹配）: {len(scores)} 个评分")
                return scores

            # 5. 如果以上都失败，尝试更宽松的模式：只提取数字对
            # 查找类似 "片段0: 0.8" 或 "[0] 0.8" 的模式
            loose_pattern = r'(?:片段|片段\s*|[\[])\s*(\d+)\s*[:\]]\s*([\d.]+)'
            loose_matches = re.findall(loose_pattern, text)
            if loose_matches:
                scores = [{"index": int(idx), "score": float(score)} for idx, score in loose_matches]
                logger.info(f"Reranker 解析成功（宽松模式）: {len(scores)} 个评分")
                return scores

            # 6. 最后的尝试：如果文本中包含数字，尝试提取所有浮点数作为分数
            all_numbers = re.findall(r'\b\d+\.\d+\b', text)
            if len(all_numbers) >= doc_count:
                # 取前 doc_count 个数字作为分数
                scores = [{"index": i, "score": float(all_numbers[i])} for i in range(doc_count)]
                logger.info(f"Reranker 解析成功（数字提取）: {len(scores)} 个评分")
                return scores

            logger.warning(f"Reranker 所有解析方式均失败，使用默认分数 0.5")
            logger.warning(f"完整响应内容: {text}")

        except Exception as e:
            logger.warning(f"Reranker 评分解析异常: {e}")
            logger.warning(f"完整响应内容: {response}")

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
