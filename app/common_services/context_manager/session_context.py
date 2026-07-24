from copy import deepcopy
from datetime import datetime
from typing import Any


class SessionContextStore:
    """Owner-scoped context cache; persistence adapters can replace this API."""

    _contexts: dict[str, dict[str, Any]] = {}

    def get(self, session_id: str, actor_id: int) -> dict[str, Any]:
        stored = self._contexts.get(session_id)
        if not stored or stored["actor_id"] != actor_id:
            return {}
        return deepcopy(stored["context"])

    def update(self, session_id: str, actor_id: int, entities: dict[str, Any], **values: Any) -> dict[str, Any]:
        existing = self.get(session_id, actor_id)
        context = {
            **existing,
            **values,
            "entities": {**existing.get("entities", {}), **entities},
            "updated_at": datetime.now().isoformat(),
        }
        self._contexts[session_id] = {"actor_id": actor_id, "context": context}
        return deepcopy(context)
