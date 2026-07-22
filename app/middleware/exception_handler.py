"""全局异常处理中间件

统一返回格式：{"code": int, "message": str, "data": null, "trace_id": str}
"""

import uuid
from fastapi import Request
from fastapi.responses import JSONResponse
from app.utils.exceptions import AppException
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """处理已知业务异常"""
    trace_id = str(uuid.uuid4())
    logger.warning(f"[{trace_id}] AppException: code={exc.code} message={exc.message}")
    return JSONResponse(
        status_code=200,  # 业务异常返回 200，通过 code 字段区分
        content={
            "code": exc.code,
            "message": exc.message,
            "data": None,
            "trace_id": trace_id,
        },
    )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """处理未知异常（兜底）"""
    trace_id = str(uuid.uuid4())
    logger.error(f"[{trace_id}] Unhandled exception: {type(exc).__name__}: {exc}", exc_info=True)

    # 生产环境可脱敏，开发/测试阶段返回详细信息
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "message": f"服务器内部错误: {str(exc)}",
            "data": None,
            "trace_id": trace_id,
        },
    )


def register_exception_handlers(app):
    """在 FastAPI app 上注册全局异常处理器"""
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)
