"""
MinIO Tool — 对象存储文件操作
封装 MinIO 客户端，提供知识库文档的上传/下载/删除
"""

import io
from typing import Optional
from pathlib import Path

from app.config.database import get_minio_client
from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger("tool.minio")
settings = get_settings()


class MinioTool:
    """MinIO 文件操作工具"""

    def __init__(self):
        self.bucket = settings.minio.bucket_docs  # knowledge-docs

    def _ensure_bucket(self):
        """确保 Bucket 存在"""
        client = get_minio_client()
        if not client.bucket_exists(self.bucket):
            client.make_bucket(self.bucket)
            logger.info(f"MinIO Bucket 创建成功: {self.bucket}")

    def upload_file(self, file_path: str, object_name: Optional[str] = None) -> str:
        """
        上传本地文件到 MinIO

        Args:
            file_path: 本地文件路径
            object_name: MinIO 中的对象名，默认使用文件名
        Returns:
            MinIO 对象路径
        """
        client = get_minio_client()
        self._ensure_bucket()

        path = Path(file_path)
        if object_name is None:
            object_name = path.name

        client.fput_object(self.bucket, object_name, file_path)
        logger.info(f"MinIO 上传成功: {object_name} ({path.stat().st_size} bytes)")
        return object_name

    def upload_bytes(self, data: bytes, object_name: str, content_type: str = "application/octet-stream") -> str:
        """
        上传字节数据到 MinIO

        Args:
            data: 文件字节内容
            object_name: MinIO 对象名
            content_type: MIME 类型
        Returns:
            MinIO 对象路径
        """
        client = get_minio_client()
        self._ensure_bucket()

        stream = io.BytesIO(data)
        client.put_object(
            self.bucket, object_name, stream, len(data), content_type=content_type
        )
        logger.info(f"MinIO 上传成功: {object_name} ({len(data)} bytes)")
        return object_name

    def download_file(self, object_name: str) -> bytes:
        """
        从 MinIO 下载文件

        Args:
            object_name: MinIO 对象名
        Returns:
            文件字节内容
        """
        client = get_minio_client()
        response = client.get_object(self.bucket, object_name)
        try:
            data = response.read()
            logger.info(f"MinIO 下载成功: {object_name} ({len(data)} bytes)")
            return data
        finally:
            response.close()
            response.release_conn()

    def delete_file(self, object_name: str):
        """
        从 MinIO 删除文件

        Args:
            object_name: MinIO 对象名
        """
        client = get_minio_client()
        client.remove_object(self.bucket, object_name)
        logger.info(f"MinIO 删除成功: {object_name}")

    def file_exists(self, object_name: str) -> bool:
        """检查文件是否存在"""
        try:
            client = get_minio_client()
            client.stat_object(self.bucket, object_name)
            return True
        except Exception:
            return False


# 全局单例
_minio_tool: Optional[MinioTool] = None


def get_minio_tool() -> MinioTool:
    """获取 MinIO 工具单例"""
    global _minio_tool
    if _minio_tool is None:
        _minio_tool = MinioTool()
    return _minio_tool
