"""
数据库 ORM 实体模型
基于 SQL 设计草稿中的核心表 + 数据库实际结构
约定：所有时间字段统一使用 create_time / update_time（与数据库一致）
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from sqlalchemy import (
    BigInteger, String, Integer, Date, DateTime, Numeric,
    JSON, Text, Index, Boolean,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.config.database import Base


class SysUser(Base):
    """统一用户表"""
    __tablename__ = "sys_user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    user_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="CUSTOMER/EMPLOYEE")
    employee_role: Mapped[Optional[str]] = mapped_column(String(32), comment="理财顾问/风控专员/客户经理/管理员")
    customer_level: Mapped[Optional[str]] = mapped_column(String(16), comment="普通/金卡/白金/钻石/私行")
    real_name: Mapped[Optional[str]] = mapped_column(String(64))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    id_card: Mapped[Optional[str]] = mapped_column(String(18))
    email: Mapped[Optional[str]] = mapped_column(String(128))
    education: Mapped[Optional[str]] = mapped_column(String(32), comment="学历")
    occupation: Mapped[Optional[str]] = mapped_column(String(64), comment="职业")
    age: Mapped[Optional[int]] = mapped_column(Integer)
    id_card_expiry: Mapped[Optional[date]] = mapped_column(Date, comment="身份证有效期")
    status: Mapped[str] = mapped_column(String(16), default="正常")
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class FinCustomerProfile(Base):
    """客户画像主表"""
    __tablename__ = "fin_customer_profile"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    risk_level: Mapped[Optional[str]] = mapped_column(String(16), comment="保守型/稳健型/平衡型/进取型/激进型")
    risk_score: Mapped[Optional[int]] = mapped_column(Integer, comment="综合评分 0-100")
    investment_experience: Mapped[Optional[str]] = mapped_column(String(16), comment="投资经验")
    annual_income_range: Mapped[Optional[str]] = mapped_column(String(32))
    total_assets: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    asset_allocation: Mapped[Optional[dict]] = mapped_column(JSON)
    product_preference: Mapped[Optional[dict]] = mapped_column(JSON)
    confidence_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), default=0.50, comment="画像综合置信度")
    basic_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), comment="维度一：基础属性得分")
    experience_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), comment="维度二：投资经验得分")
    risk_pref_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), comment="维度三：风险偏好得分")
    behavior_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), comment="维度四：行为异常得分")
    profile_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="完整画像JSON")
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class CustomerTag(Base):
    """画像标签表"""
    __tablename__ = "customer_tag"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    tag_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="标签名（如 risk_preference）")
    tag_value: Mapped[str] = mapped_column(String(128), nullable=False, comment="标签值（如 稳健型）")
    source: Mapped[str] = mapped_column(String(32), nullable=False, comment="questionnaire/ai_extract/self_report/default")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0.5, comment="标签置信度")
    valid_until: Mapped[Optional[date]] = mapped_column(Date, comment="有效期")
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("idx_customer_tag", "customer_id", "tag_name"),
    )


class RiskScoreRecord(Base):
    """评分过程记录表"""
    __tablename__ = "risk_score_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    rating_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    basic_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), comment="基础属性评分")
    experience_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), comment="投资经验评分")
    risk_pref_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), comment="风险偏好评分")
    behavior_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), comment="行为异常评分")
    total_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), comment="综合评分")
    risk_level: Mapped[Optional[str]] = mapped_column(String(16), comment="评定等级 C1-C5")
    detail_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="各子项评分明细")
    circuit_breakers: Mapped[Optional[dict]] = mapped_column(JSON, comment="触发的熔断规则")
    trigger_type: Mapped[str] = mapped_column(String(32), default="manual", comment="manual/auto/event")
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class RiskAssessment(Base):
    """风险评估问卷记录"""
    __tablename__ = "fin_risk_assessment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    assessment_date: Mapped[date] = mapped_column(Date, nullable=False, comment="评估日期")
    total_score: Mapped[Optional[int]] = mapped_column(Integer, comment="问卷总分 0-100")
    risk_level: Mapped[Optional[str]] = mapped_column(String(16), comment="C1-C5")
    answers: Mapped[Optional[dict]] = mapped_column(JSON, comment="答题明细")
    assessor_type: Mapped[Optional[str]] = mapped_column(String(16), default="AI评估", comment="评估方式: AI评估/人工评估")
    valid_until: Mapped[Optional[date]] = mapped_column(Date, comment="有效截止日期")
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class RiskRule(Base):
    """规则配置表"""
    __tablename__ = "risk_rule"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, comment="规则编号（如 FM-01）")
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="规则名称")
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="scoring/circuit_breaker")
    dimension: Mapped[Optional[str]] = mapped_column(String(32), comment="所属维度")
    config_json: Mapped[dict] = mapped_column(JSON, comment="规则配置（分值表、阈值等）")
    weight: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), comment="权重")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    version: Mapped[str] = mapped_column(String(16), default="1.0", comment="版本号")
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class FinRiskAlert(Base):
    """风控预警记录表"""
    __tablename__ = "fin_risk_alert"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, comment="预警编号")
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    transaction_id: Mapped[Optional[str]] = mapped_column(String(64))
    alert_type: Mapped[str] = mapped_column(String(32), default="large_transaction")
    alert_level: Mapped[str] = mapped_column(String(8), nullable=False, comment="low/medium/high")
    trigger_rules: Mapped[Optional[dict]] = mapped_column(JSON, comment="触发的规则列表")
    confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 2))
    trigger_detail: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", comment="pending/processing/resolved/false_positive")
    handler_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    handle_note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class ProductRecommendation(Base):
    """推荐结果表"""
    __tablename__ = "product_recommendation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), comment="会话ID")
    product_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="推荐产品代码")
    match_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), comment="匹配评分")
    score_detail: Mapped[Optional[dict]] = mapped_column(JSON, comment="评分明细")
    reasoning: Mapped[Optional[str]] = mapped_column(Text, comment="推荐理由")
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="推荐时间")
