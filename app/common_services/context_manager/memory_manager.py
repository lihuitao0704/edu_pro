from app.common_services.context_manager.session_context import SessionContextStore
from app.model.entities import FinChatSession


class MemoryManager:
    """Shared owner-scoped session memory facade.

    The existing Redis `SessionMemory` remains the short-message cache; this
    facade owns platform context state so agents do not manage it directly.
    """

    def __init__(self, session_store: SessionContextStore | None = None, db=None):
        self.session_store = session_store or SessionContextStore()
        self.db = db

    async def load_context(self, session_id: str, actor_id: int) -> dict:
        cached = self.session_store.get(session_id, actor_id)
        if cached or self.db is None or not hasattr(self.db, "get"):
            return cached
        persisted = await self.db.get(FinChatSession, session_id)
        if persisted is None or int(persisted.user_id) != actor_id:
            return {}
        return self.session_store.update(
            session_id, actor_id, (persisted.context_json or {}).get("entities", {}),
            **{key: value for key, value in (persisted.context_json or {}).items() if key != "entities"},
        )

    def save_context(self, session_id: str, actor_id: int, entities: dict, **values: object) -> dict:
        return self.session_store.update(session_id, actor_id, entities, **values)
