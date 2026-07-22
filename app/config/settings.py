"""
环境配置中心
基于 pydantic-settings 从 .env 文件加载所有配置
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional, List
from functools import lru_cache


class MySQLSettings(BaseSettings):
    """MySQL 数据库配置"""
    host: str = Field(default="127.0.0.1", alias="MYSQL_HOST")
    port: int = Field(default=3306, alias="MYSQL_PORT")
    user: str = Field(default="root", alias="MYSQL_USER")
    password: str = Field(default="", alias="MYSQL_PASSWORD")
    database: str = Field(default="wealth_manager", alias="MYSQL_DATABASE")
    pool_size: int = Field(default=10, alias="MYSQL_POOL_SIZE")
    pool_recycle: int = Field(default=3600, alias="MYSQL_POOL_RECYCLE")
    echo: bool = Field(default=False, alias="MYSQL_ECHO")

    @property
    def url(self) -> str:
        return f"mysql+pymysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}?charset=utf8mb4"

    model_config = {"env_file": ".env", "extra": "ignore"}


class RedisSettings(BaseSettings):
    """Redis 缓存配置"""
    host: str = Field(default="127.0.0.1", alias="REDIS_HOST")
    port: int = Field(default=6379, alias="REDIS_PORT")
    password: Optional[str] = Field(default=None, alias="REDIS_PASSWORD")
    db: int = Field(default=0, alias="REDIS_DB")
    max_connections: int = Field(default=20, alias="REDIS_MAX_CONNECTIONS")
    profile_ttl: int = Field(default=604800, alias="REDIS_PROFILE_TTL")    # 7天
    session_ttl: int = Field(default=1800, alias="REDIS_SESSION_TTL")     # 30分钟

    @property
    def url(self) -> str:
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"

    model_config = {"env_file": ".env", "extra": "ignore"}


class MilvusSettings(BaseSettings):
    """Milvus 向量数据库配置"""
    host: str = Field(default="127.0.0.1", alias="MILVUS_HOST")
    port: int = Field(default=19530, alias="MILVUS_PORT")
    collection_faq: str = Field(default="faq_knowledge", alias="MILVUS_COLLECTION_FAQ")
    collection_product: str = Field(default="product_knowledge", alias="MILVUS_COLLECTION_PRODUCT")
    collection_policy: str = Field(default="policy_knowledge", alias="MILVUS_COLLECTION_POLICY")
    dim: int = Field(default=1536, alias="MILVUS_DIM")
    top_k: int = Field(default=5, alias="MILVUS_TOP_K")
    score_threshold: float = Field(default=0.65, alias="MILVUS_SCORE_THRESHOLD")
    timeout: int = Field(default=2, alias="MILVUS_TIMEOUT")

    model_config = {"env_file": ".env", "extra": "ignore"}


class Neo4jSettings(BaseSettings):
    """Neo4j 图数据库配置"""
    uri: str = Field(default="bolt://127.0.0.1:7687", alias="NEO4J_URI")
    user: str = Field(default="neo4j", alias="NEO4J_USER")
    password: str = Field(default="", alias="NEO4J_PASSWORD")
    database: str = Field(default="neo4j", alias="NEO4J_DATABASE")
    timeout: int = Field(default=3, alias="NEO4J_TIMEOUT")

    model_config = {"env_file": ".env", "extra": "ignore"}


class MinIOSettings(BaseSettings):
    """MinIO 对象存储配置"""
    endpoint: str = Field(default="127.0.0.1:9000", alias="MINIO_ENDPOINT")
    access_key: str = Field(default="minioadmin", alias="MINIO_ACCESS_KEY")
    secret_key: str = Field(default="", alias="MINIO_SECRET_KEY")
    bucket_docs: str = Field(default="knowledge-docs", alias="MINIO_BUCKET_DOCS")
    secure: bool = Field(default=False, alias="MINIO_SECURE")

    model_config = {"env_file": ".env", "extra": "ignore"}


class LLMSettings(BaseSettings):
    """大模型配置"""
    # OpenAI
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_model_chat: str = Field(default="gpt-4o", alias="OPENAI_MODEL_CHAT")
    openai_model_embedding: str = Field(default="text-embedding-3-small", alias="OPENAI_MODEL_EMBEDDING")
    openai_temperature: float = Field(default=0.7, alias="OPENAI_TEMPERATURE")
    openai_max_tokens: int = Field(default=2048, alias="OPENAI_MAX_TOKENS")
    openai_timeout: int = Field(default=30, alias="OPENAI_TIMEOUT")
    openai_max_retries: int = Field(default=3, alias="OPENAI_MAX_RETRIES")
    openai_retry_delays: str = Field(default="1,2,4", alias="OPENAI_RETRY_DELAYS")

    # 本地备用模型
    local_enabled: bool = Field(default=False, alias="LOCAL_MODEL_ENABLED")
    local_base_url: str = Field(default="http://127.0.0.1:8000/v1", alias="LOCAL_MODEL_BASE_URL")
    local_model_chat: str = Field(default="qwen2.5-7b", alias="LOCAL_MODEL_CHAT")
    local_model_embedding: str = Field(default="bge-large-zh", alias="LOCAL_MODEL_EMBEDDING")

    @property
    def retry_delays(self) -> List[int]:
        return [int(x.strip()) for x in self.openai_retry_delays.split(",")]

    model_config = {"env_file": ".env", "extra": "ignore"}


class JWTSettings(BaseSettings):
    """JWT 认证配置"""
    secret_key: str = Field(default="dev-secret-key-change-in-production", alias="JWT_SECRET_KEY")
    algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    expire_minutes: int = Field(default=1440, alias="JWT_EXPIRE_MINUTES")
    mock_mode: bool = Field(default=True, alias="AUTH_MOCK_MODE")

    model_config = {"env_file": ".env", "extra": "ignore"}


class RAGSettings(BaseSettings):
    """RAG 知识库配置"""
    chunk_size: int = Field(default=512, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=64, alias="CHUNK_OVERLAP")
    sse_enabled: bool = Field(default=True, alias="SSE_ENABLED")
    sse_chunk_size: int = Field(default=50, alias="SSE_CHUNK_SIZE")

    model_config = {"env_file": ".env", "extra": "ignore"}


class ProfileSettings(BaseSettings):
    """画像研判配置"""
    confidence_decay_rate: float = Field(default=0.2, alias="PROFILE_CONFIDENCE_DECAY_RATE")
    confidence_evidence_gain: float = Field(default=0.05, alias="PROFILE_CONFIDENCE_EVIDENCE_GAIN")
    confidence_gain_max: float = Field(default=0.3, alias="PROFILE_CONFIDENCE_GAIN_MAX")
    confidence_conflict_penalty: float = Field(default=0.1, alias="PROFILE_CONFIDENCE_CONFLICT_PENALTY")
    drift_threshold: float = Field(default=0.6, alias="PROFILE_DRIFT_THRESHOLD")

    model_config = {"env_file": ".env", "extra": "ignore"}


class RecommendationSettings(BaseSettings):
    """推荐引擎配置"""
    weight_risk: float = Field(default=0.40, alias="RECOMMEND_WEIGHT_RISK")
    weight_preference: float = Field(default=0.25, alias="RECOMMEND_WEIGHT_PREFERENCE")
    weight_diversity: float = Field(default=0.20, alias="RECOMMEND_WEIGHT_DIVERSITY")
    weight_return_term: float = Field(default=0.15, alias="RECOMMEND_WEIGHT_RETURN_TERM")
    top_n: int = Field(default=3, alias="RECOMMEND_TOP_N")

    model_config = {"env_file": ".env", "extra": "ignore"}


class NL2SQLSettings(BaseSettings):
    """NL2SQL 安全配置"""
    max_rows: int = Field(default=100, alias="NL2SQL_MAX_ROWS")
    blocked_keywords: str = Field(default="DROP,DELETE,UPDATE,INSERT,ALTER,TRUNCATE,CREATE",
                                   alias="NL2SQL_BLOCKED_KEYWORDS")

    @property
    def blocked_list(self) -> List[str]:
        return [kw.strip().upper() for kw in self.blocked_keywords.split(",")]

    model_config = {"env_file": ".env", "extra": "ignore"}


class GraphRAGSettings(BaseSettings):
    """GraphRAG 融合检索配置"""
    vector_weight: float = Field(default=0.6, alias="GRAPHRAG_VECTOR_WEIGHT")
    graph_weight: float = Field(default=0.4, alias="GRAPHRAG_GRAPH_WEIGHT")

    model_config = {"env_file": ".env", "extra": "ignore"}


class LogSettings(BaseSettings):
    """日志配置"""
    level: str = Field(default="INFO", alias="LOG_LEVEL")
    file: str = Field(default="logs/app.log", alias="LOG_FILE")
    max_bytes: int = Field(default=10485760, alias="LOG_MAX_BYTES")
    backup_count: int = Field(default=5, alias="LOG_BACKUP_COUNT")

    model_config = {"env_file": ".env", "extra": "ignore"}


class Settings(BaseSettings):
    """全局配置聚合类"""

    mysql: MySQLSettings = MySQLSettings()
    redis: RedisSettings = RedisSettings()
    milvus: MilvusSettings = MilvusSettings()
    neo4j: Neo4jSettings = Neo4jSettings()
    minio: MinIOSettings = MinIOSettings()
    llm: LLMSettings = LLMSettings()
    jwt: JWTSettings = JWTSettings()
    rag: RAGSettings = RAGSettings()
    profile: ProfileSettings = ProfileSettings()
    recommendation: RecommendationSettings = RecommendationSettings()
    nl2sql: NL2SQLSettings = NL2SQLSettings()
    graphrag: GraphRAGSettings = GraphRAGSettings()
    log: LogSettings = LogSettings()

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    """获取全局配置单例"""
    return Settings()


# 快捷引用
settings = get_settings()
