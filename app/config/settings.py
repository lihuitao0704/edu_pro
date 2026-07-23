"""
环境配置中心
基于 pydantic-settings 从 .env 文件加载所有配置
"""

from dotenv import load_dotenv

# 先把 .env 注入 os.environ，确保所有 os.getenv 调用都能读到配置
# （llm_client.py 等模块用 os.getenv 读取，不走 pydantic settings 对象）
load_dotenv()

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional, List
from functools import lru_cache


class MySQLSettings(BaseSettings):
    host: str = Field(default="127.0.0.1", alias="MYSQL_HOST")
    port: int = Field(default=3306, alias="MYSQL_PORT")
    user: str = Field(default="root", alias="MYSQL_USER")
    password: str = Field(default="", alias="MYSQL_PASSWORD")
    database: str = Field(default="wealth_manager", alias="MYSQL_DATABASE")
    pool_size: int = Field(default=10, alias="MYSQL_POOL_SIZE")
    pool_recycle: int = Field(default=3600, alias="MYSQL_POOL_RECYCLE")
    echo: bool = Field(default=False, alias="MYSQL_ECHO")
    model_config = {"env_file": ".env", "extra": "ignore"}


class RedisSettings(BaseSettings):
    host: str = Field(default="127.0.0.1", alias="REDIS_HOST")
    port: int = Field(default=6379, alias="REDIS_PORT")
    password: Optional[str] = Field(default=None, alias="REDIS_PASSWORD")
    db: int = Field(default=0, alias="REDIS_DB")
    max_connections: int = Field(default=20, alias="REDIS_MAX_CONNECTIONS")
    profile_ttl: int = Field(default=604800, alias="REDIS_PROFILE_TTL")
    session_ttl: int = Field(default=1800, alias="REDIS_SESSION_TTL")
    model_config = {"env_file": ".env", "extra": "ignore"}


class MilvusSettings(BaseSettings):
    host: str = Field(default="127.0.0.1", alias="MILVUS_HOST")
    port: int = Field(default=19530, alias="MILVUS_PORT")
    dim: int = Field(default=1024, alias="MILVUS_DIM")
    top_k: int = Field(default=5, alias="MILVUS_TOP_K")
    score_threshold: float = Field(default=0.65, alias="MILVUS_SCORE_THRESHOLD")
    timeout: int = Field(default=5, alias="MILVUS_TIMEOUT")
    collection_faq: str = Field(default="faq_knowledge", alias="MILVUS_COLLECTION_FAQ")
    collection_product: str = Field(default="product_knowledge", alias="MILVUS_COLLECTION_PRODUCT")
    collection_policy: str = Field(default="policy_knowledge", alias="MILVUS_COLLECTION_POLICY")
    model_config = {"env_file": ".env", "extra": "ignore"}


class Neo4jSettings(BaseSettings):
    uri: str = Field(default="bolt://127.0.0.1:7687", alias="NEO4J_URI")
    user: str = Field(default="neo4j", alias="NEO4J_USER")
    password: str = Field(default="", alias="NEO4J_PASSWORD")
    database: str = Field(default="neo4j", alias="NEO4J_DATABASE")
    timeout: int = Field(default=3, alias="NEO4J_TIMEOUT")
    model_config = {"env_file": ".env", "extra": "ignore"}


class MinIOSettings(BaseSettings):
    endpoint: str = Field(default="127.0.0.1:9000", alias="MINIO_ENDPOINT")
    access_key: str = Field(default="minioadmin", alias="MINIO_ACCESS_KEY")
    secret_key: str = Field(default="", alias="MINIO_SECRET_KEY")
    bucket_docs: str = Field(default="knowledge-docs", alias="MINIO_BUCKET_DOCS")
    secure: bool = Field(default=False, alias="MINIO_SECURE")
    model_config = {"env_file": ".env", "extra": "ignore"}


class LLMSettings(BaseSettings):
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_model_chat: str = Field(default="gpt-4o", alias="OPENAI_MODEL_CHAT")
    ollama_embed_url: str = Field(default="http://127.0.0.1:11434", alias="OLLAMA_EMBED_URL")
    ollama_model_embedding: str = Field(default="bge-m3", alias="OPENAI_MODEL_EMBEDDING")
    openai_temperature: float = Field(default=0.7, alias="OPENAI_TEMPERATURE")
    openai_max_tokens: int = Field(default=2048, alias="OPENAI_MAX_TOKENS")
    openai_timeout: int = Field(default=30, alias="OPENAI_TIMEOUT")
    openai_max_retries: int = Field(default=3, alias="OPENAI_MAX_RETRIES")
    openai_retry_delays: str = Field(default="1,2,4", alias="OPENAI_RETRY_DELAYS")
    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def retry_delays_list(self) -> list:
        return [int(x) for x in self.openai_retry_delays.split(",")]


class JWTSettings(BaseSettings):
    secret_key: str = Field(default="dev-secret-key-change-in-production", alias="JWT_SECRET_KEY")
    algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    expire_minutes: int = Field(default=1440, alias="JWT_EXPIRE_MINUTES")
    mock_mode: bool = Field(default=True, alias="AUTH_MOCK_MODE")
    model_config = {"env_file": ".env", "extra": "ignore"}


class ProfileSettings(BaseSettings):
    confidence_decay_rate: float = Field(default=0.2, alias="PROFILE_CONFIDENCE_DECAY_RATE")
    confidence_evidence_gain: float = Field(default=0.05, alias="PROFILE_CONFIDENCE_EVIDENCE_GAIN")
    confidence_gain_max: float = Field(default=0.3, alias="PROFILE_CONFIDENCE_GAIN_MAX")
    confidence_conflict_penalty: float = Field(default=0.1, alias="PROFILE_CONFIDENCE_CONFLICT_PENALTY")
    drift_threshold: float = Field(default=0.6, alias="PROFILE_DRIFT_THRESHOLD")
    model_config = {"env_file": ".env", "extra": "ignore"}


class RecommendationSettings(BaseSettings):
    weight_risk: float = Field(default=0.40, alias="RECOMMEND_WEIGHT_RISK")
    weight_preference: float = Field(default=0.25, alias="RECOMMEND_WEIGHT_PREFERENCE")
    weight_diversity: float = Field(default=0.20, alias="RECOMMEND_WEIGHT_DIVERSITY")
    weight_return_term: float = Field(default=0.15, alias="RECOMMEND_WEIGHT_RETURN_TERM")
    top_n: int = Field(default=3, alias="RECOMMEND_TOP_N")
    model_config = {"env_file": ".env", "extra": "ignore"}


class GraphRAGSettings(BaseSettings):
    vector_weight: float = Field(default=0.6, alias="GRAPHRAG_VECTOR_WEIGHT")
    graph_weight: float = Field(default=0.4, alias="GRAPHRAG_GRAPH_WEIGHT")
    model_config = {"env_file": ".env", "extra": "ignore"}


class LogSettings(BaseSettings):
    level: str = Field(default="INFO", alias="LOG_LEVEL")
    file: str = Field(default="logs/app.log", alias="LOG_FILE")
    max_bytes: int = Field(default=10485760, alias="LOG_MAX_BYTES")
    backup_count: int = Field(default=5, alias="LOG_BACKUP_COUNT")
    model_config = {"env_file": ".env", "extra": "ignore"}


class SecuritySettings(BaseSettings):
    """安全配置"""
    cors_origins: str = Field(default="*", alias="CORS_ORIGINS")
    # 开发阶段默认允许所有，生产环境请在 .env 中配置白名单:
    # CORS_ORIGINS=http://localhost:3000,https://wealth.example.com

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = {"env_file": ".env", "extra": "ignore"}


class NL2SQLSettings(BaseSettings):
    max_rows: int = Field(default=100, alias="NL2SQL_MAX_ROWS")
    blocked_keywords: str = Field(default="DROP,DELETE,UPDATE,INSERT,ALTER,TRUNCATE,CREATE", alias="NL2SQL_BLOCKED_KEYWORDS")

    @property
    def blocked_keywords_list(self) -> list[str]:
        return [k.strip() for k in self.blocked_keywords.split(",") if k.strip()]

    model_config = {"env_file": ".env", "extra": "ignore"}


class SSESettings(BaseSettings):
    enabled: bool = Field(default=True, alias="SSE_ENABLED")
    chunk_size: int = Field(default=50, alias="SSE_CHUNK_SIZE")
    model_config = {"env_file": ".env", "extra": "ignore"}


class ChunkSettings(BaseSettings):
    size: int = Field(default=512, alias="CHUNK_SIZE")
    overlap: int = Field(default=64, alias="CHUNK_OVERLAP")
    model_config = {"env_file": ".env", "extra": "ignore"}


class LongCatSettings(BaseSettings):
    api_key: str = Field(default="", alias="LONGCAT_API_KEY")
    base_url: str = Field(default="https://api.longcat.chat/openai", alias="LONGCAT_BASE_URL")
    model: str = Field(default="LongCat-2.0", alias="LONGCAT_MODEL")
    model_config = {"env_file": ".env", "extra": "ignore"}


class Settings(BaseSettings):
    mysql: MySQLSettings = MySQLSettings()
    redis: RedisSettings = RedisSettings()
    milvus: MilvusSettings = MilvusSettings()
    neo4j: Neo4jSettings = Neo4jSettings()
    minio: MinIOSettings = MinIOSettings()
    llm: LLMSettings = LLMSettings()
    jwt: JWTSettings = JWTSettings()
    profile: ProfileSettings = ProfileSettings()
    recommendation: RecommendationSettings = RecommendationSettings()
    graphrag: GraphRAGSettings = GraphRAGSettings()
    log: LogSettings = LogSettings()
    nl2sql: NL2SQLSettings = NL2SQLSettings()
    sse: SSESettings = SSESettings()
    chunk: ChunkSettings = ChunkSettings()
    longcat: LongCatSettings = LongCatSettings()
    security: SecuritySettings = SecuritySettings()
    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
