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

        检索用户最近的 assistant 回复，提取为偏好摘要文本。
        如果无历史记录，返回空字符串。
        """
        archives = await db.execute(
            select(ConversationArchive)
            .where(
                ConversationArchive.user_id == user_id,
                ConversationArchive.role == "assistant",
            )
            .order_by(ConversationArchive.create_time.desc())
            .limit(limit)
        )
        records = archives.scalars().all()
        if not records:
            return ""

        # 去重 + 截取关键片段
        seen: set[str] = set()
        snippets: list[str] = []
        for record in records:
            content = (record.content or "").strip()
            if not content or content in seen:
                continue
            # 只取前 100 字，避免 prompt 过长
            snippet = content[:100]
            seen.add(content)
            snippets.append(snippet)

        if not snippets:
            return ""

        preferences = "；".join(snippets)
        summary = f"历史对话摘要：{preferences}。"
        logger.info(
            f"召回历史偏好 | user_id={user_id} | 记录数={len(snippets)}"
        )
        return summary


def get_memory_recall_service() -> UserMemoryRecallService:
    """获取记忆召回服务单例"""
    return UserMemoryRecallService()
