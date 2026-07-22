"""
知识库初始化导入脚本

用法：
    cd 项目根目录
    python -m scripts.init_knowledge

或：
    python scripts/init_knowledge.py
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

from app.config.database import async_session_factory, init_db, init_milvus
from app.service.knowledge_service import get_knowledge_service
from app.utils.logger import get_logger

logger = get_logger("scripts.init_knowledge")

# 文档导入配置
# 格式：(文件路径, 知识类型)
KNOWLEDGE_DOCS = [
    # FAQ 类（公司信息）
    ("data/knowledge/公司信息/高频问答对.txt", "FAQ"),

    # 产品说明类（公司业务）
    ("data/knowledge/公司业务/个人理财产品手册.md", "产品说明"),
    ("data/knowledge/公司业务/企业金融服务方案.md", "产品说明"),
    ("data/knowledge/公司业务/高净值客户服务规范.md", "产品说明"),

    # 政策法规类（金融政策）
    ("data/knowledge/金融政策/个人投资者适当性管理指南.md", "政策法规"),
    ("data/knowledge/金融政策/反洗钱合规操作手册.md", "政策法规"),
    ("data/knowledge/金融政策/理财产品销售管理办法.md", "政策法规"),
]


async def main():
    """主入口"""
    print("=" * 60)
    print("  智能财富管家 — 知识库初始化导入")
    print("=" * 60)

    # 1. 初始化数据库连接
    print("\n[1/3] 初始化数据库连接...")
    try:
        await init_db()
        print("  MySQL: OK")
    except Exception as e:
        print(f"  MySQL: 连接失败 ({e})")
        print("  请检查 .env 中的 MySQL 配置是否正确")
        return

    try:
        init_milvus()
        print("  Milvus: OK")
    except Exception as e:
        print(f"  Milvus: 连接失败 ({e})")
        print("  请检查 .env 中的 Milvus 配置是否正确")
        return

    # 2. 检查文档是否存在
    print("\n[2/3] 检查文档文件...")
    docs_to_import = []
    for file_path, knowledge_type in KNOWLEDGE_DOCS:
        full_path = project_root / file_path
        if full_path.exists():
            docs_to_import.append((str(full_path), knowledge_type))
            print(f"  [OK] {file_path} → {knowledge_type}")
        else:
            print(f"  [MISS] {file_path} — 文件不存在，跳过")

    if not docs_to_import:
        print("\n  没有找到可导入的文档，请检查 data/knowledge/ 目录")
        return

    print(f"\n  共 {len(docs_to_import)} 个文档待导入")

    # 3. 批量导入
    print("\n[3/3] 开始导入...")
    success_count = 0
    fail_count = 0

    async with async_session_factory() as db:
        service = get_knowledge_service(db)

        for file_path, knowledge_type in docs_to_import:
            file_name = Path(file_path).name
            print(f"\n  导入中: {file_name} ({knowledge_type})")

            try:
                result = await service.ingest_document(
                    file_path=file_path,
                    knowledge_type=knowledge_type,
                    title=Path(file_path).stem,
                )
                print(f"  ✓ 成功 | ID={result['knowledge_id']} | "
                      f"分块={result['chunk_count']}")
                success_count += 1

            except Exception as e:
                print(f"  ✗ 失败: {e}")
                fail_count += 1

    # 4. 汇总
    print("\n" + "=" * 60)
    print(f"  导入完成！成功: {success_count} | 失败: {fail_count}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
