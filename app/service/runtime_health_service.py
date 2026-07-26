"""In-process dependency health signals updated by real runtime calls."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock


_lock = Lock()
_llm_state = {
    "status": "unknown",
    "checked_at": None,
    "error_type": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mark_llm_success() -> None:
    with _lock:
        _llm_state.update(
            {"status": "ok", "checked_at": _now(), "error_type": None}
        )


def mark_llm_failure(exc: Exception) -> None:
    with _lock:
        _llm_state.update(
            {
                "status": "unavailable",
                "checked_at": _now(),
                "error_type": type(exc).__name__,
            }
        )


def get_runtime_health() -> dict:
    with _lock:
        return {"llm": dict(_llm_state)}
