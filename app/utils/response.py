"""统一响应格式"""

import uuid
from typing import Any, Optional
from fastapi.responses import JSONResponse


def success(data: Any = None, message: str = "success") -> dict:
    return {
        "code": 200,
        "message": message,
        "data": data,
        "trace_id": str(uuid.uuid4()),
    }


def error(code: int = 400, message: str = "error", data: Any = None) -> dict:
    return {
        "code": code,
        "message": message,
        "data": data,
        "trace_id": str(uuid.uuid4()),
    }


def json_response(data: Any = None, message: str = "success", code: int = 200) -> JSONResponse:
    return JSONResponse(
        content={
            "code": code,
            "message": message,
            "data": data,
            "trace_id": str(uuid.uuid4()),
        },
        status_code=code,
    )
