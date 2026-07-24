"""
UserMemoryRecallService — 用户记忆召回服务
跨 session 记忆闭环的核心组件：从持久化存储中召回用户画像摘要和历史偏好，
注入到 Agent prompt 中，使 Agent "记住"用户。
"""

from typing import Optional

from sqlalchemy import select

from app.model.entities import (
    ConversationArchive,
    CustomerTag,
    FinCustomerProfile,
    SysUser,
)
from app.utils.logger import get_logger

logger = get_logger("service.memory_recall")


class UserMemoryRecallService:
    """用户记忆召回服务：画像摘要 + 历史偏好"""

    async def build_user_profile_summary(self, db, user_id: int) -> str:
        """
        从持久化数据构建用户画像摘要文本，直接注入 prompt。

        包含：基础信息、风险等级、客户等级、关键标签。
        如果没有任何数据，返回空字符串（调用方应跳过注入）。
        """
        parts: list[str] = []

        # 用户基础信息
        user = await db.get(SysUser, user_id)
        if not user:
            return ""

        # 客户画像
        profile = await db.execute(
            select(FinCustomerProfile).where(
                FinCustomerProfile.customer_id == user_id
            )
        )
        profile = profile.scalar_one_or_none()

        if profile:
            if profile.risk_level:
                parts.append(f"风险等级：{profile.risk_level}")
            if profile.risk_score is not None:
                parts.append(f"风险评分：{profile.risk_score}分")
            if profile.investment_experience:
                parts.append(f"投资经验：{profile.investment_experience}")
            if profile.annual_income_range:
                parts.append(f"年收入：{profile.annual_income_range}")
            if profile.total_assets is not None:
                parts.append(f"总资产：{float(profile.total_assets):.0f}元")
            if profile.risk_flag and profile.risk_flag != "normal":
                parts.append(f"风险标记：{profile.risk_flag}")

        if user.customer_level:
            parts.append(f"客户等级：{user.customer_level}")

        # 关键标签（最近 5 个）
        tags = await db.execute(
            select(CustomerTag)
            .where(CustomerTag.customer_id == user_id)
            .order_by(CustomerTag.create_time.desc())
            .limit(5)
        )
        tag_list = tags.scalars().all()
        if tag_list:
            tag_strs = [f"{t.tag_name}={t.tag_value}" for t in tag_list]
            parts.append(f"标签：{', '.join(tag_strs)}")

        if not parts:
            return ""

        summary = "客户画像：" + "；".join(parts) + "。"
        logger.info(f"构建用户画像摘要 | user_id={user_id} | 字段数={len(parts)}")
        return summary

    async def recall_historical_preferences(
        self, db, user_id: int, limit: int = 5
    ) -> str:
        """
        从历史对话归档中召回用户偏好摘要。

        同时检索用户最近的 user+assistant 对话对，构建有上下文的记忆摘要。
        如果无历史记录，返回空字符串。
        """
        # 获取最近的对话记录（同时包含 user 和 assistant）
        archives = await db.execute(
            select(ConversationArchive)
            .where(ConversationArchive.user_id == user_id)
            .order_by(ConversationArchive.create_time.desc())
            .limit(limit * 2)  # 取双倍以覆盖 user+assistant 对
        )
        records = archives.scalars().all()
        if not records:
            return ""

        # 按 session_id 分组，取最近 session 的用户问题
        seen_sessions: dict[str, list] = {}
        for record in records:
            sid = record.session_id or "unknown"
            if sid not in seen_sessions:
                seen_sessions[sid] = []
            seen_sessions[sid].append(record)

        # 构建有上下文的记忆摘要
        context_parts: list[str] = []
        for sid, msgs in list(seen_sessions.items())[:limit]:
            # 取该 session 的第一条用户消息作为"用户曾问过"
            user_msgs = [m for m in msgs if m.role == "user"]
            if user_msgs:
                first_user_msg = user_msgs[-1]  # 最旧的用户消息
                content = (first_user_msg.content or "").strip()[:80]
                if content:
                    context_parts.append(f"曾问过: {content}")

        if not context_parts:
            return ""

        summary = "历史记忆：" + "；".join(context_parts) + "。"
        logger.info(
            f"召回历史记忆 | user_id={user_id} | session数={len(context_parts)}"
        )
        return summary

    async def recall_recent_conversations(
        self, db, user_id: int, max_sessions: int = 3, max_msgs_per_session: int = 4
    ) -> str:
        """
        召回用户最近几次会话的对话摘要（完整 user+assistant 对话对）。

        用于注入 LLM prompt，使 Agent 了解用户近期都在聊什么。
        返回格式化的对话文本，无历史时返回空字符串。
        """
        # 获取该用户最近的所有对话
        archives = await db.execute(
            select(ConversationArchive)
            .where(ConversationArchive.user_id == user_id)
            .order_by(ConversationArchive.create_time.desc())
            .limit(50)  # 先取一批再按 session 分组
        )
        records = archives.scalars().all()
        if not records:
            return ""

        # 按 session 分组（保持时间顺序）
        from collections import OrderedDict
        sessions: OrderedDict = OrderedDict()
        for record in reversed(records):  # 从旧到新遍历
            sid = record.session_id or "unknown"
            if sid not in sessions:
                sessions[sid] = []
            sessions[sid].append(record)

        # 取最近的几个 session
        recent_sids = list(sessions.keys())[-max_sessions:]

        lines: list[str] = []
        for sid in recent_sids:
            msgs = sessions[sid][-max_msgs_per_session:]  # 每个 session 最多取几条
            session_lines = []
            for msg in msgs:
                role_label = "用户" if msg.role == "user" else "助手"
                content = (msg.content or "").strip()[:120]
                if content:
                    session_lines.append(f"  {role_label}: {content}")
            if session_lines:
                lines.append(f"[历史会话 {sid[:8]}...]")
                lines.extend(session_lines)

        if not lines:
            return ""

        result = "以下是该用户近期的历史对话记录（供参考，帮助理解用户背景）：\n" + "\n".join(lines)
        logger.info(f"召回历史对话 | user_id={user_id} | session数={len(recent_sids)}")
        return result


def get_memory_recall_service() -> UserMemoryRecallService:
    """获取记忆召回服务单例"""
    return UserMemoryRecallService()
