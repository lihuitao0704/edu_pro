"""
环境配置中心
基于 pydantic-settings 从 .env 文件加载所有配置
"""

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
    dim: int = Field(default=1536, alias="MILVUS_DIM")
    top_k: int = Field(default=5, alias="MILVUS_TOP_K")
    score_threshold: float = Field(default=0.65, alias="MILVUS_SCORE_THRESHOLD")
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
    ollama_model_embedding: str = Field(default="bge-m3", alias="OLLAMA_MODEL_EMBEDDING")
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
    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
