"""应用配置模块，使用 pydantic-settings 管理所有配置项。"""

from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用全局配置，支持从环境变量和 .env 文件加载。

    重要：所有敏感配置（数据库连接、密钥等）都应该通过环境变量设置，
         不要依赖默认值，确保生产环境安全。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,  # 环境变量大小写不敏感
        extra="ignore",  # 忽略 .env 中多余的变量
    )

    # ---- 应用基本配置 ----
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    APP_NAME: str = "stockmate"
    APP_VERSION: str = "0.1.0"
    API_PREFIX: str = "/api/v1"

    # ---- Logging ----
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "text"] = "text"
    LOG_COLOR: bool = True
    LOG_TIMEZONE: str = "Asia/Shanghai"
    LOG_TO_FILE: bool = True
    LOG_DIR: str = "logs"
    LOG_RETENTION_DAYS: int = 30
    LOG_SERVICE_NAME: str = "backend"
    LOG_LEVEL_OVERRIDES_STR: str = "apscheduler=WARNING,httpx=WARNING,httpcore=WARNING"
    ACCESS_LOG_ENABLED: bool = True
    ACCESS_LOG_LEVEL: str = "INFO"
    ACCESS_LOG_EXCLUDE_PATHS_STR: str = "/health"

    @property
    def LOG_LEVEL_OVERRIDES(self) -> dict[str, str]:
        overrides: dict[str, str] = {}
        for item in self.LOG_LEVEL_OVERRIDES_STR.split(","):
            if not item.strip():
                continue
            logger_name, separator, level = item.partition("=")
            if not separator or not logger_name.strip() or not level.strip():
                raise ValueError("LOG_LEVEL_OVERRIDES_STR 必须使用 logger=LEVEL 格式")
            overrides[logger_name.strip()] = level.strip().upper()
        return overrides

    @property
    def ACCESS_LOG_EXCLUDE_PATHS(self) -> set[str]:
        return {path.strip() for path in self.ACCESS_LOG_EXCLUDE_PATHS_STR.split(",") if path.strip()}

    # ---- 安全与认证配置 ----
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # Access Token 默认 1 小时
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7  # Refresh Token 默认 7 天
    # Cookie 安全配置
    COOKIE_SECURE: bool = False  # 生产环境设为 True (HTTPS only)
    COOKIE_SAMESITE: str = "lax"  # Lax 允许跨站导航时发送 Cookie
    ACCESS_TOKEN_COOKIE_NAME: str = "access_token"
    REFRESH_TOKEN_COOKIE_NAME: str = "refresh_token"

    # ---- CORS 配置 ----
    # 从环境变量读取，按照格式编排：http://localhost:5173,http://localhost:3000
    CORS_ORIGINS_STR: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000"

    @property
    def CORS_ORIGINS(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS_STR.split(",") if origin.strip()]

    # ---- 数据库配置 ----
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/stockmate"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_ECHO: bool = False

    # ---- Redis 配置 ----
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: Optional[str] = None

    # ---- 基金累计收益率走势快照 ----
    FUND_TREND_CACHE_TTL_SECONDS: int = 86400
    FUND_TREND_FRESH_SECONDS: int = 86400

    # ---- AI 模型配置 ----
    AI_API_KEY: str = ""
    AI_BASE_URL: str = "https://api.openai.com/v1"
    AI_MODEL_NAME: str = "gpt-4o"
    AI_TEMPERATURE: float = 0.7
    AI_MAX_TOKENS: int = 4096

    # ---- AI Embedding 配置 ----
    AI_EMBEDDING_API_KEY: str = ""
    AI_EMBEDDING_BASE_URL: str = "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    AI_EMBEDDING_MODEL: str = "qwen3.7-text-embedding"
    AI_EMBEDDING_DIM: int = 1024
    AI_EMBEDDING_BATCH_SIZE: int = 10
    AI_EMBEDDING_REQUEST_DIMENSIONS: int = 1024
    AI_EMBEDDING_TIMEOUT_SECONDS: int = 60  # 访问服务商embedding模型的超时时间
    AI_EMBEDDING_MAX_RETRIES: int = 3
    AI_EMBEDDING_RETRY_BASE_SECONDS: float = 2.0  # 重试时需要等待的时间 指数退避

    # ---- RAG 流水线配置 ----
    RAG_PIPELINE_SWITCH: bool = False
    # 立刻执行RAG流水线当新增资讯新闻后
    RAG_PIPELINE_ON_NEWS_CRAWL: bool = True
    # RAG流水线最小间隔时间
    RAG_PIPELINE_MIN_INTERVAL_SECONDS: int = 60
    # RAG补偿任务时间
    RAG_RECONCILE_INTERVAL_SECONDS: int = 3600
    # RAG流水线最大批次
    RAG_PIPELINE_DRAIN_MAX_BATCHES: int = 5
    # RAG流水线过程最大时间
    RAG_PIPELINE_DRAIN_MAX_SECONDS: int = 180
    # RAG流水线同步新闻/资讯数量
    RAG_PIPELINE_NEWS_LIMIT: int = 100
    # 最大切片数量
    RAG_PIPELINE_CHUNK_LIMIT: int = 100
    # 最大向量化数据量
    RAG_PIPELINE_EMBED_LIMIT: int = 100
    # 最大字符数
    RAG_PIPELINE_MAX_CHARS: int = 800
    # 重叠字符数
    RAG_PIPELINE_OVERLAP_CHARS: int = 120

    # ---- 备用 AI 模型配置（Ollama / DeepSeek 等） ----
    AI_OLLAMA_BASE_URL: str = "http://localhost:11434"
    AI_OLLAMA_MODEL: str = "qwen2.5:7b"
    AI_DEEPSEEK_API_KEY: str = ""
    AI_DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    AI_DEEPSEEK_MODEL: str = "deepseek-chat"

    # ---- 用户级 AI 模型配置 ----
    AI_MODEL_CONFIG_ENCRYPTION_KEY: str = ""
    AI_MODEL_CONFIG_ENCRYPTION_KEY_ID: str = "default"
    AI_MODEL_CONFIG_ALLOW_HTTP_BASE_URL: bool = False
    AI_MODEL_CONFIG_ALLOW_PRIVATE_BASE_URL: bool = False
    AI_MODEL_CONFIG_TEST_TIMEOUT_SECONDS: float = 30.0

    # ---- Lightweight LangGraph agent runtime ----
    LANGGRAPH_DATABASE_URL: Optional[str] = None  # LangGraph Checkpoint数据库地址 不填复用当前数据库链接
    AGENT_RUN_POLL_SECONDS: float = 0.5  # Worker查询待执行Run的间隔
    AGENT_RUN_LEASE_SECONDS: int = 120  # Worker持有Run的租约时间
    AGENT_EVENT_STREAM_TTL_SECONDS: int = 86400  # Redis流事件保留时间
    AGENT_EVENT_STREAM_MAXLEN: int = 10000  # 每个Run最多保留的Redis事件数
    AGENT_STREAM_BLOCK_MS: int = 10000  # SSE读取Redis时的阻塞等待时间
    AGENT_SNAPSHOT_INTERVAL_SECONDS: float = 0.5  # 部分回答写入PostgreSQL的间隔

    # ---- 定时任务配置 ----
    SCHEDULER_TIMEZONE: str = "Asia/Shanghai"
    NEWS_CRAWL_INTERVAL_SECONDS: int = 60

    def validate_required_settings(self) -> None:
        """验证必需的配置项，在生产环境必须设置。"""
        if not self.DATABASE_URL.startswith("postgresql"):
            raise ValueError("DATABASE_URL 必须使用 PostgreSQL")

        if not self.DEBUG:
            if not self.SECRET_KEY:
                raise ValueError("在非 DEBUG 模式下，SECRET_KEY 环境变量必须设置")
            if not self.AI_MODEL_CONFIG_ENCRYPTION_KEY:
                raise ValueError("在非 DEBUG 模式下，AI_MODEL_CONFIG_ENCRYPTION_KEY 环境变量必须设置")


settings = Settings()

settings.validate_required_settings()
