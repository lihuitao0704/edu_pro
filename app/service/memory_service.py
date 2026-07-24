"""
Memory Service — 记忆管理服务
统一封装短期记忆（Redis 会话）+ 长期记忆（MySQL 归档）
"""

import asyncio
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.session_memory import SessionMemory
from app.model.entities import ConversationArchive
from app.utils.logger import get_logger

logger = get_logger("service.memory")


class MemoryService:
    """记忆管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_history(self, session_id: str) -> list[dict]:
        """
        获取会话历史（短期记忆）

        Args:
            session_id: 会话 ID
        Returns:
            消息列表 [{"role": "user/assistant", "content": "...", "timestamp": ...}]
        """
        memory = SessionMemory(session_id)
        messages = await memory.get_messages()
        return messages

    async def save_message(self, session_id: str, role: str, content: str):
        """
        保存消息到短期记忆

        Args:
            session_id: 会话 ID
            role: 角色（user / assistant / system）
            content: 消息内容
        """
        memory = SessionMemory(session_id)
        await memory.add_message(role, content)

    async def archive_conversation(
        self,
        session_id: str,
        user_id: int,
        agent_type: str,
        role: str,
        content: str,
        tool_calls: Optional[dict] = None,
    ):
        """
        异步归档会话到 MySQL（长期记忆）

        Args:
            session_id: 会话 ID
            user_id: 用户 ID
            agent_type: Agent 类型（customer_service / advisor / profile）
            role: 角色
            content: 内容
            tool_calls: 工具调用记录
        """
        try:
            archive = ConversationArchive(
                session_id=session_id,
                user_id=user_id,
                agent_type=agent_type,
                role=role,
                content=content,
                tool_calls=tool_calls,
            )
            self.db.add(archive)
            await self.db.commit()
            logger.info(f"会话归档成功 | session={session_id} | role={role}")
        except Exception as e:
            logger.error(f"会话归档失败: {e}")
            await self.db.rollback()

    async def archive_turn(
        self,
        session_id: str,
        user_id: int,
        agent_type: str,
        user_content: str,
        assistant_content: str,
    ) -> None:
        """Persist a complete turn before the caller returns its response."""
        try:
            self.db.add(ConversationArchive(
                session_id=session_id,
                user_id=user_id,
                agent_type=agent_type,
                role="user",
                content=user_content,
            ))
            self.db.add(ConversationArchive(
                session_id=session_id,
                user_id=user_id,
                agent_type=agent_type,
                role="assistant",
                content=assistant_content,
            ))
            await self.db.commit()
            logger.info(f"conversation turn archived | session={session_id}")
        except Exception as e:
            logger.error(f"conversation turn archive failed: {e}")
            await self.db.rollback()
            raise RuntimeError("conversation turn archive failed") from e

    def archive_conversation_bg(
        self,
        session_id: str,
        user_id: int,
        agent_type: str,
        role: str,
        content: str,
        tool_calls: Optional[dict] = None,
    ):
        """
        后台异步归档（不阻塞主流程）
        注意：需要在事件循环中调用
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在已有事件循环中创建后台任务
                asyncio.create_task(
                    self._archive_bg_task(session_id, user_id, agent_type, role, content, tool_calls)
                )
            else:
                loop.run_until_complete(
                    self.archive_conversation(session_id, user_id, agent_type, role, content, tool_calls)
                )
        except Exception as e:
            logger.warning(f"后台归档启动失败: {e}")

    async def _archive_bg_task(
        self,
        session_id: str,
        user_id: int,
        agent_type: str,
        role: str,
        content: str,
        tool_calls: Optional[dict],
    ):
        """后台归档任务（使用独立 session）"""
        from app.config.database import async_session_factory
        async with async_session_factory() as session:
            try:
                archive = ConversationArchive(
                    session_id=session_id,
                    user_id=user_id,
                    agent_type=agent_type,
                    role=role,
                    content=content,
                    tool_calls=tool_calls,
                )
                session.add(archive)
                await session.commit()
                logger.info(f"后台归档成功 | session={session_id} | role={role}")
            except Exception as e:
                logger.error(f"后台归档失败: {e}")
                await session.rollback()


def get_memory_service(db: AsyncSession) -> MemoryService:
    """获取记忆服务实例"""
    return MemoryService(db)
