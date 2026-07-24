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
    JSON, Text, ForeignKey, Index,Boolean
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
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
    balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
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
    risk_flag: Mapped[Optional[str]] = mapped_column(String(16), comment="风险标记: normal/warning/high — 风控事件驱动更新")
    profile_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="完整画像JSON")
    calibration_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="最新双轨校准结果快照")
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


class FinCalibrationRecord(Base):
    """双轨校准历史记录（自评画像 vs 行为真实画像）"""
    __tablename__ = "fin_calibration_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    calibrate_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="校准执行时间")
    direction: Mapped[str] = mapped_column(String(32), nullable=False, comment="over_optimistic/over_conservative/aligned")
    self_reported: Mapped[Optional[dict]] = mapped_column(JSON, comment="自评画像快照")
    behavioral: Mapped[Optional[dict]] = mapped_column(JSON, comment="行为推断画像")
    triggered_rules: Mapped[Optional[dict]] = mapped_column(JSON, comment="触发的校准规则列表（含证据）")
    summary: Mapped[Optional[str]] = mapped_column(Text, comment="面向投顾的可读校准摘要")
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
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    alert_type: Mapped[str] = mapped_column(String(32), default="large_transaction")
    alert_level: Mapped[str] = mapped_column(String(8), nullable=False, comment="low/medium/high")
    trigger_detail: Mapped[Optional[str]] = mapped_column(Text)
    transaction_ids: Mapped[Optional[dict]] = mapped_column(JSON, comment="关联交易ID+触发的规则")
    status: Mapped[Optional[str]] = mapped_column(String(16), default="pending", comment="pending/processing/resolved/false_positive")
    handler_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    handle_result: Mapped[Optional[str]] = mapped_column(Text)
    reminder_key: Mapped[Optional[str]] = mapped_column(String(64), unique=True, comment="scheduler idempotency key")
    create_time: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="创建时间")
    update_time: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="更新时间")


class FinProduct(Base):
    """基金产品表"""
    __tablename__ = "fin_product"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    product_name: Mapped[str] = mapped_column(String(128), nullable=False)
    product_type: Mapped[Optional[str]] = mapped_column(String(32), comment="货币型/债券型/混合型/股票型")
    risk_level: Mapped[Optional[str]] = mapped_column(String(8), comment="R1-R5")
    expected_return: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 4))
    min_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 2))
    term_days: Mapped[Optional[int]] = mapped_column(Integer)
    fund_manager: Mapped[Optional[str]] = mapped_column(String(64))
    industry: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[Optional[str]] = mapped_column(String(16), default="在售")
    create_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    update_time: Mapped[Optional[datetime]] = mapped_column(DateTime)


class FinHoldings(Base):
    """客户持仓表"""
    __tablename__ = "fin_holdings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    shares: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    cost_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    current_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    profit_loss: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    profit_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4))
    status: Mapped[Optional[str]] = mapped_column(String(16), default="持有中")
    create_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    update_time: Mapped[Optional[datetime]] = mapped_column(DateTime)


class FinTransaction(Base):
    """交易流水表"""
    __tablename__ = "fin_transaction"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    transaction_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    transaction_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="purchase/redeem/transfer")
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    shares: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    nav: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6), comment="净值")
    fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    status: Mapped[Optional[str]] = mapped_column(String(16), default="已确认")
    operator_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    remark: Mapped[Optional[str]] = mapped_column(String(255))
    create_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    update_time: Mapped[Optional[datetime]] = mapped_column(DateTime)


class BizWorkOrder(Base):
    """业务工单表"""
    __tablename__ = "biz_work_order"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    work_order_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    order_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="投诉/建议/咨询/故障")
    sub_type: Mapped[Optional[str]] = mapped_column(String(32))
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    submitter_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    handler_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    current_node: Mapped[Optional[str]] = mapped_column(String(32), default="待处理")
    priority: Mapped[Optional[str]] = mapped_column(String(8), default="普通")
    status: Mapped[Optional[str]] = mapped_column(String(16), default="待处理")
    biz_content: Mapped[Optional[dict]] = mapped_column(JSON)
    remark: Mapped[Optional[str]] = mapped_column(String(255))
    create_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    update_time: Mapped[Optional[datetime]] = mapped_column(DateTime)


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
