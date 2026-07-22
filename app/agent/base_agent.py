"""Agent 基类 — 统一执行骨架"""

from abc import ABC, abstractmethod
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.memory.session_memory import SessionMemory


class BaseAgent(ABC):
    """Agent 统一执行骨架"""

    def __init__(self, db: AsyncSession, session_id: str = ""):
        self.db = db
        self.session_id = session_id
        self.memory = SessionMemory(session_id) if session_id else None

    @abstractmethod
    async def execute(self, message: str, **kwargs) -> dict:
        """
        执行 Agent 主流程
        message: 用户输入
        kwargs: 额外参数（如 customer_id）
        """
        pass

    async def _recall_memory(self) -> list:
        """从会话记忆中召回上下文"""
        if self.memory:
            return await self.memory.get_messages()
        return []

    async def _save_to_memory(self, role: str, content: str):
        """保存对话到短期记忆"""
        if self.memory:
            await self.memory.add_message(role, content)

    async def _extend_session(self):
        """续期会话"""
        if self.memory:
            await self.memory.extend_ttl()
