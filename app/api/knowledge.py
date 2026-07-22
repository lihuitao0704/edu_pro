"""
Knowledge API — 知识库管理接口
"""

import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.model.schemas import KnowledgeUploadResponse, KnowledgeListItem
from app.service.knowledge_service import get_knowledge_service
from app.utils.response import success
from app.utils.exceptions import AppException

router = APIRouter()


@router.post("/upload", response_model=dict)
async def upload_knowledge(
    file: UploadFile = File(...),
    knowledge_type: str = Form(...),
    title: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """
    上传知识文档

    支持格式：txt, md, docx
    知识类型：FAQ, 产品说明, 政策法规, 操作指南
    """
    # 验证文件类型
    if not file.filename:
        raise AppException("文件名不能为空")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in [".txt", ".md", ".docx"]:
        raise AppException("仅支持 txt, md, docx 格式文件")

    # 验证知识类型
    valid_types = ["FAQ", "产品说明", "政策法规", "操作指南"]
    if knowledge_type not in valid_types:
        raise AppException(f"知识类型必须是：{', '.join(valid_types)}")

    # 保存临时文件
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # 入库
        service = get_knowledge_service(db)
        result = await service.ingest_document(
            file_path=tmp_path,
            knowledge_type=knowledge_type,
            title=title or file.filename,
        )

        return success(data=result)
    finally:
        # 清理临时文件
        Path(tmp_path).unlink(missing_ok=True)


@router.get("/list", response_model=dict)
async def list_knowledge(
    knowledge_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    查询知识列表
    """
    service = get_knowledge_service(db)
    items = await service.list_knowledge(
        knowledge_type=knowledge_type,
        status=status,
        page=page,
        size=size,
    )
    total = await service.count_knowledge(
        knowledge_type=knowledge_type,
        status=status,
    )

    return success(data={
        "items": items,
        "total": total,
        "page": page,
        "size": size,
    })


@router.delete("/{knowledge_id}", response_model=dict)
async def delete_knowledge(
    knowledge_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    删除知识文档
    """
    service = get_knowledge_service(db)
    deleted = await service.delete_knowledge(knowledge_id)

    if not deleted:
        raise AppException("知识文档不存在")

    return success(data={"deleted": True})


@router.post("/search", response_model=dict)
async def search_knowledge(
    query: str = Form(...),
    knowledge_type: Optional[str] = Form(None),
    top_k: int = Form(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    """
    知识检索接口

    独立检索，返回最相关的知识片段
    """
    service = get_knowledge_service(db)
    results = await service.search_knowledge(
        query=query,
        knowledge_type=knowledge_type,
        top_k=top_k,
    )

    return success(data={"results": results})
