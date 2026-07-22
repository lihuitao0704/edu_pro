"""
Pydantic 数据模型（请求/响应 Schema）
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Dict
from pydantic import BaseModel, Field


# ==================== 画像相关 ====================

class DimensionDetail(BaseModel):
    """维度子项明细"""
    age: Optional[int] = None
    education: Optional[int] = None
    occupation: Optional[int] = None
    income: Optional[int] = None
    assets: Optional[int] = None
    years: Optional[int] = None
    complexity: Optional[int] = None
    frequency: Optional[int] = None
    returns: Optional[int] = None
    assessment: Optional[int] = None
    emotional_deduction: Optional[int] = None
    loss_tolerance: Optional[int] = None
    abnormal_count: Optional[int] = None
    abnormal_risk_level: Optional[str] = Field(None, alias="risk_level")


class DimensionScore(BaseModel):
    """维度得分"""
    score: float
    detail: Optional[DimensionDetail] = None


class ProfileResult(BaseModel):
    """画像研判结果"""
    customer_id: int
    risk_level: str
    risk_score: Optional[int] = None
    total_score: float
    dimensions: Dict[str, DimensionScore]
    confidence_score: float
    circuit_breakers: List[dict] = []
    warnings: List[str] = []
    recommended_products: List[str] = []


class ProfileUpdateRequest(BaseModel):
    """画像更新请求"""
    tags: List[Dict[str, str]] = Field(..., description="[{tag_name, tag_value, source}]")
    force_update: bool = False


class ProfileAssessRequest(BaseModel):
    """画像研判请求（customer_id 优先取路径参数，请求体中的可选）"""
    customer_id: Optional[int] = Field(None, description="客户ID，不填则取路径参数")
    trigger_type: str = "manual"


# ==================== 风评相关 ====================

class QuestionnaireItem(BaseModel):
    """问卷题目"""
    q: int = Field(..., description="题号")
    question: str
    options: List[Dict[str, str]] = Field(..., description="[{A: 描述, score: 分值}]")


class AssessmentAnswer(BaseModel):
    """答题"""
    q: int
    a: str


class AssessmentRequest(BaseModel):
    """风评提交请求"""
    customer_id: int
    answers: List[AssessmentAnswer]


class AssessmentResult(BaseModel):
    """风评结果"""
    customer_id: int
    total_score: int
    risk_level: str
    valid_until: date


class SuitabilityCheckRequest(BaseModel):
    """适当性匹配请求"""
    customer_id: int
    product_code: str


class SuitabilityCheckResult(BaseModel):
    """适当性匹配结果"""
    match: bool
    customer_level: str
    product_level: str
    warning: Optional[str] = None


# ==================== 投顾推荐 ====================

class AdvisorChatRequest(BaseModel):
    """投顾对话请求"""
    session_id: str
    message: str
    user_id: int
    customer_id: Optional[int] = None


class ProductRecommend(BaseModel):
    """推荐产品"""
    product_code: str
    product_name: str
    risk_level: str
    expected_return: Optional[float] = None
    match_score: Optional[float] = None
    reason: str


class AdvisorChatResponse(BaseModel):
    """投顾对话响应"""
    reply: str
    recommendations: List[ProductRecommend] = []
    customer_profile: Optional[dict] = None
    reasoning: Optional[str] = None
    session_id: str


class RecommendRequest(BaseModel):
    """纯产品推荐请求"""
    customer_id: int
    top_n: int = 3
    risk_level: Optional[str] = None  # 可选：指定风险等级筛选


class AllocationRequest(BaseModel):
    """资产配置请求"""
    customer_id: int


class AllocationResult(BaseModel):
    """资产配置结果"""
    customer_id: int
    risk_level: str
    allocation: Dict[str, float]
    explanation: str


# ==================== 标签相关 ====================

class TagItem(BaseModel):
    """标签项"""
    tag_name: str
    tag_value: str
    source: str = "ai_extract"
    confidence: Optional[float] = None


class LabelExtractRequest(BaseModel):
    """LLM 标签提取请求"""
    customer_id: int
    conversation_text: str


# ==================== 统一响应 ====================

class ApiResponse(BaseModel):
    """统一 API 响应"""
    code: int = 200
    message: str = "success"
    data: Optional[dict] = None
    trace_id: str


# ==================== 智能客服Agent ====================

class CustomerChatRequest(BaseModel):
    """客服对话请求"""
    session_id: str
    message: str
    user_id: int


class SourceReference(BaseModel):
    """来源引用"""
    title: str
    source_file: str
    chunk_index: int = 0
    score: float = 0.0
    content_snippet: str = ""


class CustomerChatResponse(BaseModel):
    """客服对话响应"""
    reply: str
    sources: List[SourceReference] = []
    session_id: str
    intent: str = ""
    confidence: float = 0.0


class KnowledgeUploadResponse(BaseModel):
    """知识上传响应"""
    knowledge_id: int
    title: str
    chunk_count: int


class KnowledgeListItem(BaseModel):
    """知识列表项"""
    id: int
    knowledge_type: str
    title: str
    source_file: Optional[str] = None
    status: str = "有效"
    create_time: Optional[datetime] = None


class KnowledgeSearchRequest(BaseModel):
    """知识检索请求"""
    query: str
    knowledge_type: Optional[str] = None  # faq / product / policy
    top_k: int = 5


# ==================== 风控监测（Phase 4） ====================


class TransactionEvent(BaseModel):
    """交易事件 — POST /api/risk/monitor 请求体"""
    customer_id: int = Field(..., description="客户ID")
    transaction_id: str = Field(..., description="交易流水号")
    amount: float = Field(..., ge=0, description="交易金额")
    transaction_type: str = Field(..., description="交易类型: cash/transfer/purchase/redeem")
    currency: str = Field(default="CNY")
    counterparty: Optional[dict] = Field(default=None)
    timestamp: str = Field(..., description="交易时间 ISO8601")


class AlertHandleRequest(BaseModel):
    """处理预警请求体"""
    action: str = Field(..., description="处理动作: resolved/false_positive")
    handler_id: int = Field(..., description="风控专员ID")
    handle_note: str = Field(default="", description="处理备注")


class MonitorResponse(BaseModel):
    """POST /api/risk/monitor 响应"""
    alert: Optional[dict] = Field(default=None)
    triggered_count: int = Field(default=0)

# ==================== NL2SQL 数据分析 ====================

class QueryRequest(BaseModel):
    """数据分析查询请求"""
    session_id: str = Field(..., description="会话ID，用于关联上下文")
    message: str = Field(..., description="用户自然语言查询问题")
    user_id: int = Field(..., description="操作用户ID")


class QueryResponse(BaseModel):
    """数据分析查询响应"""
    reply: str = Field(..., description="自然语言解读")
    sql: Optional[str] = Field(None, description="生成的SQL语句")
    query_result: Optional[List[Dict]] = Field(None, description="查询结果列表")
    session_id: str = Field(..., description="会话ID")
    error: Optional[str] = Field(None, description="错误信息")
