"""
FAQ 知识重新切片 & 向量入库脚本

功能：
    1. 清空 Milvus faq_knowledge 集合中的旧向量
    2. 清理 MySQL fin_knowledge_meta 中 knowledge_type="FAQ" 的旧记录
    3. 读取高频问答对.txt，使用增强后的 DocumentParser 按 TSV FAQ 格式分块
    4. 批量生成 Embedding → Milvus 入库
    5. 写入新的 MySQL 元数据记录

用法：
    cd 项目根目录
    python -m scripts.reindex_faq
    或: python scripts/reindex_faq.py
"""

import asyncio
import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 切换工作目录到项目根目录（确保 .env 能被正确加载）
os.chdir(project_root)

from pymilvus import utility, Collection
from sqlalchemy import select

from app.config.database import async_session_factory, init_db, init_milvus
from app.tool.document_parser import get_document_parser
from app.tool.embedding_tool import get_embedding_tool
from app.tool.milvus_tool import get_milvus_tool, COLLECTION_CONFIGS
from app.model.entities import FinKnowledgeMeta
from app.utils.logger import get_logger

logger = get_logger("scripts.reindex_faq")

# FAQ 数据源
FAQ_FILE = "data/knowledge/公司信息/高频问答对.txt"
FAQ_COLLECTION = "faq_knowledge"
KNOWLEDGE_TYPE = "FAQ"


async def main():
    print("=" * 60)
    print("  智能财富管家 — FAQ 知识重新切片 & 向量入库")
    print("=" * 60)

    # 1. 初始化数据库连接
    print("\n[1/5] 初始化数据库连接...")
    try:
        await init_db()
        print("  MySQL: OK")
    except Exception as e:
        print(f"  MySQL: 连接失败 ({e})")
        return

    try:
        init_milvus()
        print("  Milvus: OK")
    except Exception as e:
        print(f"  Milvus: 连接失败 ({e})")
        return

    # 2. 删除并重建 Milvus faq_knowledge 集合（新增 question/answer 字段）
    print("\n[2/5] 删除并重建 Milvus faq_knowledge 集合（新增 question/answer 字段）...")
    milvus_tool = get_milvus_tool()
    try:
        if utility.has_collection(FAQ_COLLECTION):
            # 删除旧集合（schema 变更需要重建）
            utility.drop_collection(FAQ_COLLECTION)
            print("  已删除旧集合")

        # 重新创建集合（带 question/answer 字段）
        config = COLLECTION_CONFIGS.get(FAQ_COLLECTION, {})
        milvus_tool.ensure_collection(FAQ_COLLECTION, index_type=config.get("index_type", "HNSW"))
        print("  集合已重建（包含 question/answer 字段）")
    except Exception as e:
        print(f"  Milvus 重建失败: {e}")
        return

    # 3. 清理 MySQL 旧元数据
    print("\n[3/5] 清理 MySQL 旧 FAQ 元数据...")
    async with async_session_factory() as db:
        stmt = select(FinKnowledgeMeta).where(
            FinKnowledgeMeta.knowledge_type == KNOWLEDGE_TYPE
        )
        result = await db.execute(stmt)
        old_records = result.scalars().all()
        for record in old_records:
            record.status = "过期"
        await db.commit()
        print(f"  已标记 {len(old_records)} 条旧记录为过期")

    # 4. 读取 FAQ 文件 & 分块
    print("\n[4/5] 解析 FAQ 文件 & 分块...")
    faq_path = project_root / FAQ_FILE
    if not faq_path.exists():
        print(f"  文件不存在: {faq_path}")
        return

    parser = get_document_parser()
    text = parser.parse(str(faq_path))
    base_metadata = {"source": faq_path.name, "title": faq_path.stem}
    chunks = parser.chunk_text(text, chunk_size=512, overlap=64, metadata=base_metadata)

    if not chunks:
        print("  分块结果为空，请检查文件格式")
        return

    # 检查是否走了 TSV FAQ 分块
    faq_chunks = [c for c in chunks if c["metadata"].get("chunk_type") == "faq"]
    text_chunks = [c for c in chunks if c["metadata"].get("chunk_type") == "text"]
    print(f"  总分块数: {len(chunks)}")
    print(f"  FAQ 分块: {len(faq_chunks)} | 文本分块: {len(text_chunks)}")

    if not faq_chunks:
        print("  ⚠ 未检测到 FAQ 格式分块，可能文件格式不匹配")
        confirm = input("  是否继续入库？(y/N): ").strip().lower()
        if confirm != "y":
            print("  已取消")
            return

    # 5. 生成 Embedding & Milvus 入库
    print("\n[5/5] 生成 Embedding & Milvus 入库...")
    contents = [chunk["content"] for chunk in chunks]

    # 提取 question 和 answer（用于 faq_knowledge 集合的独立字段）
    questions = []
    answers = []
    for chunk in chunks:
        content = chunk["content"]
        # 从 "Q: xxx\nA: xxx" 格式中提取
        if content.startswith("Q: ") and "\nA: " in content:
            parts = content.split("\nA: ", 1)
            q = parts[0].replace("Q: ", "", 1)
            a = parts[1] if len(parts) > 1 else ""
            questions.append(q)
            answers.append(a)
        else:
            # 兜底：整条作为 question，answer 留空
            questions.append(content)
            answers.append("")

    embedding_tool = get_embedding_tool()
    embeddings = await embedding_tool.encode_batch(contents)
    print(f"  Embedding 生成完成 | 数量={len(embeddings)} | 维度={len(embeddings[0])}")

    # 创建 MySQL 元数据记录
    async with async_session_factory() as db:
        meta = FinKnowledgeMeta(
            knowledge_type=KNOWLEDGE_TYPE,
            title=faq_path.stem,
            source_file=faq_path.name,
            milvus_collection=FAQ_COLLECTION,
            status="有效",
        )
        db.add(meta)
        await db.flush()
        knowledge_id = meta.id

        # 为每个 chunk 的 metadata 添加 source_id
        metadatas = []
        for chunk in chunks:
            chunk_meta = {**chunk["metadata"], "source_id": knowledge_id}
            metadatas.append(chunk_meta)

        # Milvus 入库（传递 question 和 answer）
        milvus_tool.insert(
            collection_name=FAQ_COLLECTION,
            embeddings=embeddings,
            contents=contents,
            metadatas=metadatas,
            questions=questions,
            answers=answers,
        )

        await db.commit()

    # 6. 汇总
    print("\n" + "=" * 60)
    print(f"  FAQ 重新入库完成！")
    print(f"  知识 ID: {knowledge_id}")
    print(f"  分块数: {len(chunks)}")
    print(f"  向量维度: {len(embeddings[0])}")
    print(f"  集合: {FAQ_COLLECTION}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
