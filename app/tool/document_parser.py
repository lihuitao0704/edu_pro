"""
Document Parser — 文档解析与分块
支持 txt/md/docx 格式，针对金融知识文档的特殊分块策略
"""

import re
from pathlib import Path
from typing import Optional
from docx import Document as DocxDocument

from app.utils.logger import get_logger

logger = get_logger("tool.document_parser")


class DocumentParser:
    """文档解析工具"""

    def parse(self, file_path: str) -> str:
        """
        解析文档为纯文本

        Args:
            file_path: 文件路径（支持 .txt / .md / .docx）
        Returns:
            文档文本内容
        """
        path = Path(file_path)
        suffix = path.suffix.lower()

        if suffix == ".txt" or suffix == ".md":
            return path.read_text(encoding="utf-8")
        elif suffix == ".docx":
            return self._parse_docx(file_path)
        else:
            raise ValueError(f"不支持的文件格式: {suffix}")

    def _parse_docx(self, file_path: str) -> str:
        """解析 docx 文件"""
        doc = DocxDocument(file_path)
        paragraphs = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                # 保留标题层级信息
                if para.style.name.startswith("Heading"):
                    level = para.style.name.replace("Heading ", "")
                    paragraphs.append(f"{'#' * int(level)} {text}")
                else:
                    paragraphs.append(text)
        return "\n\n".join(paragraphs)

    def chunk_text(
        self,
        text: str,
        chunk_size: int = 512,
        overlap: int = 64,
        metadata: Optional[dict] = None,
    ) -> list[dict]:
        """
        文本分块

        Args:
            text: 待分块文本
            chunk_size: 每块最大字符数（约等于 token 数）
            overlap: 重叠字符数
            metadata: 附加元数据（source, title 等）
        Returns:
            分块列表，每项包含 content 和 metadata
        """
        metadata = metadata or {}

        # 检测是否为 FAQ 格式（Q: ... A: ...）
        if self._is_faq_format(text):
            return self._chunk_faq(text, metadata)

        # 检测是否为法规条款格式（第X条 ...）
        if self._is_regulation_format(text):
            return self._chunk_regulation(text, metadata)

        # 普通文本：按段落 + 滑动窗口分块
        return self._chunk_by_sliding_window(text, chunk_size, overlap, metadata)

    def _is_faq_format(self, text: str) -> bool:
        """检测是否为 FAQ 格式"""
        # 匹配 Q: / A: 或 问题：/ 答案： 模式
        patterns = [
            r"^Q[:：]\s*.+\nA[:：]",
            r"^问题[:：]\s*.+\n答案[:：]",
        ]
        for pattern in patterns:
            if re.search(pattern, text, re.MULTILINE):
                return True
        return False

    def _is_regulation_format(self, text: str) -> bool:
        """检测是否为法规条款格式"""
        # 匹配 第X条 / 第X章 模式
        return bool(re.search(r"第[一二三四五六七八九十百千]+[条章]", text))

    def _chunk_faq(self, text: str, metadata: dict) -> list[dict]:
        """FAQ 格式分块：每条 FAQ 独立成块"""
        chunks = []
        # 按 Q: 或 问题： 分割
        faq_pattern = r"(Q[:：]\s*.+\nA[:：]\s*.+?)(?=\nQ[:：]|\n问题[:：]|$)"
        matches = re.findall(faq_pattern, text, re.DOTALL)

        for idx, faq in enumerate(matches):
            faq = faq.strip()
            if faq:
                chunk_meta = {**metadata, "chunk_index": idx, "chunk_type": "faq"}
                chunks.append({"content": faq, "metadata": chunk_meta})

        logger.info(f"FAQ 分块完成 | 共 {len(chunks)} 条")
        return chunks

    def _chunk_regulation(self, text: str, metadata: dict) -> list[dict]:
        """法规条款分块：每条独立成块"""
        chunks = []
        # 按 第X条 分割
        article_pattern = r"(第[一二三四五六七八九十百千]+条\s*.+?)(?=第[一二三四五六七八九十百千]+条|$)"
        matches = re.findall(article_pattern, text, re.DOTALL)

        for idx, article in enumerate(matches):
            article = article.strip()
            if article:
                chunk_meta = {**metadata, "chunk_index": idx, "chunk_type": "regulation"}
                chunks.append({"content": article, "metadata": chunk_meta})

        logger.info(f"法规条款分块完成 | 共 {len(chunks)} 条")
        return chunks

    def _chunk_by_sliding_window(
        self, text: str, chunk_size: int, overlap: int, metadata: dict
    ) -> list[dict]:
        """滑动窗口分块（普通文本）"""
        chunks = []
        text = text.strip()
        if not text:
            return []

        # 先按段落分割
        paragraphs = re.split(r"\n\s*\n", text)
        current_chunk = []
        current_length = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_len = len(para)

            # 如果单个段落就超过 chunk_size，强制切分
            if para_len > chunk_size:
                if current_chunk:
                    chunk_text = "\n\n".join(current_chunk)
                    chunk_meta = {**metadata, "chunk_index": len(chunks), "chunk_type": "text"}
                    chunks.append({"content": chunk_text, "metadata": chunk_meta})
                    current_chunk = []
                    current_length = 0

                # 强制切分长段落
                for i in range(0, para_len, chunk_size - overlap):
                    sub_para = para[i : i + chunk_size]
                    chunk_meta = {**metadata, "chunk_index": len(chunks), "chunk_type": "text"}
                    chunks.append({"content": sub_para, "metadata": chunk_meta})
                continue

            # 如果加上当前段落会超过 chunk_size，保存当前块
            if current_length + para_len > chunk_size and current_chunk:
                chunk_text = "\n\n".join(current_chunk)
                chunk_meta = {**metadata, "chunk_index": len(chunks), "chunk_type": "text"}
                chunks.append({"content": chunk_text, "metadata": chunk_meta})

                # 保留 overlap 部分
                overlap_text = "\n\n".join(current_chunk)[-overlap:]
                current_chunk = [overlap_text, para]
                current_length = len(overlap_text) + para_len
            else:
                current_chunk.append(para)
                current_length += para_len

        # 保存最后一块
        if current_chunk:
            chunk_text = "\n\n".join(current_chunk)
            chunk_meta = {**metadata, "chunk_index": len(chunks), "chunk_type": "text"}
            chunks.append({"content": chunk_text, "metadata": chunk_meta})

        logger.info(f"滑动窗口分块完成 | 共 {len(chunks)} 块 | chunk_size={chunk_size}")
        return chunks


# 全局单例
_parser: Optional[DocumentParser] = None


def get_document_parser() -> DocumentParser:
    """获取文档解析器单例"""
    global _parser
    if _parser is None:
        _parser = DocumentParser()
    return _parser
