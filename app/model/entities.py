"""
数据库 ORM 实体模型
基于 SQL 设计草稿中的 10 张核心表
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from sqlalchemy import (
    BigInteger, String, Integer, Date, DateTime, Numeric,
    JSON, Text, ForeignKey, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.config.database import Base


class SysUser(Base):
    """统一用户表"""
    __tablename__ = "sys_user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    real_name: Mapped[Optional[str]] = mapped_column(String(64))
    user_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="CUSTOMER/EMPLOYEE")
    employee_role: Mapped[Optional[str]] = mapped_column(String(32), comment="理财顾问/风控专员/客户经理/管理员")
    customer_level: Mapped[Optional[str]] = mapped_column(String(16), comment="普通/金卡/白金/钻石/私行")
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    email: Mapped[Optional[str]] = mapped_column(String(128))
    id_card: Mapped[Optional[str]] = mapped_column(String(18))
    id_card_expiry: Mapped[Optional[date]] = mapped_column(Date)
    occupation: Mapped[Optional[str]] = mapped_column(String(64))
    education: Mapped[Optional[str]] = mapped_column(String(32))
    age: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="正常")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class FinCustomerProfile(Base):
    """客户画像主表"""
    __tablename__ = "fin_customer_profile"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    risk_level: Mapped[Optional[str]] = mapped_column(String(16), comment="保守型/稳健型/平衡型/进取型/激进型")
    risk_score: Mapped[Optional[int]] = mapped_column(Integer, comment="综合评分 0-100")
    investment_experience: Mapped[Optional[str]] = mapped_column(String(32))
    annual_income_range: Mapped[Optional[str]] = mapped_column(String(32))
    total_assets: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    asset_allocation: Mapped[Optional[dict]] = mapped_column(JSON)
    product_preference: Mapped[Optional[dict]] = mapped_column(JSON)
    confidence_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    basic_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), comment="维度一得分")
    experience_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), comment="维度二得分")
    risk_pref_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), comment="维度三得分")
    behavior_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), comment="维度四得分")
    profile_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="完整画像JSON")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class CustomerTag(Base):
    """画像标签表"""
    __tablename__ = "customer_tag"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    tag_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tag_value: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, comment="questionnaire/ai_extract/self_report/default")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    valid_until: Mapped[Optional[date]] = mapped_column(Date)

    __table_args__ = (
        Index("idx_customer_tag", "customer_id", "tag_name"),
    )


class RiskScoreRecord(Base):
    """评分过程记录表"""
    __tablename__ = "risk_score_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    rating_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    basic_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    experience_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    risk_pref_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    behavior_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    total_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    risk_level: Mapped[Optional[str]] = mapped_column(String(16))
    detail_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="各子项评分明细")
    circuit_breakers: Mapped[Optional[dict]] = mapped_column(JSON, comment="触发的熔断规则")
    trigger_type: Mapped[str] = mapped_column(String(32), default="manual", comment="manual/auto/event")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class RiskAssessment(Base):
    """风险评估问卷记录"""
    __tablename__ = "fin_risk_assessment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    total_score: Mapped[int] = mapped_column(Integer, nullable=False, comment="问卷总分 0-100")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, comment="C1-C5")
    answers_json: Mapped[dict] = mapped_column(JSON, comment="答题明细")
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class RiskRule(Base):
    """规则配置表"""
    __tablename__ = "risk_rule"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="scoring/circuit_breaker")
    dimension: Mapped[Optional[str]] = mapped_column(String(32))
    config_json: Mapped[dict] = mapped_column(JSON)
    weight: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    is_active: Mapped[bool] = mapped_column(default=True)
    version: Mapped[str] = mapped_column(String(16), default="1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ProductRecommendation(Base):
    """推荐结果表"""
    __tablename__ = "product_recommendation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64))
    product_code: Mapped[str] = mapped_column(String(32), nullable=False)
    match_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    score_detail: Mapped[Optional[dict]] = mapped_column(JSON)
    reasoning: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ConversationArchive(Base):
    """会话归档表"""
    __tablename__ = "conversation_archive"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    agent_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="customer_service/advisor/profile")
    role: Mapped[str] = mapped_column(String(16), nullable=False, comment="user/assistant/system")
    content: Mapped[Optional[str]] = mapped_column(Text)
    tool_calls: Mapped[Optional[dict]] = mapped_column(JSON, comment="工具调用记录")
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_session", "session_id"),
        Index("idx_user", "user_id"),
        Index("idx_agent", "agent_type"),
    )


class FinKnowledgeMeta(Base):
    """金融知识元数据表"""
    __tablename__ = "fin_knowledge_meta"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="产品说明/政策法规/FAQ/操作指南")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_file: Mapped[Optional[str]] = mapped_column(String(255))
    minio_path: Mapped[Optional[str]] = mapped_column(String(512))
    milvus_collection: Mapped[Optional[str]] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(32), default="v1")
    status: Mapped[str] = mapped_column(String(16), default="有效", index=True, comment="有效/过期/草稿")
    expire_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
