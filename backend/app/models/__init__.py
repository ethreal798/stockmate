"""应用模型模块，导出所有 SQLAlchemy 模型和 Base。"""

from app.core.database import Base

from .base import TimestampMixin, SoftDeleteMixin, GormBaseModel
from .user import User
from .rag import (
    RagDocument,
    RagChunk,
    RagChunkEmbedding,
    RagEvent,
    RagWeeklyReport,
    RagQueryLog,
)
from .news import NewsSource, NewsRawItem, NewsItem, NewsItemTopic, NewsItemEntity, NewsItemRelation
from .settings import UserAIModelConfig
from .agent import AgentMessage, AgentRun, AgentThread, PromptTemplate
from .fund import (
    Fund,
    FundWatchlistItem,
    FundOpenRankLatest,
    FundExchangeRankLatest,
    FundMoneyRankLatest,
    FundPerformanceTrendLatest,
)

__all__ = [
    "Base",
    "TimestampMixin",
    "SoftDeleteMixin",
    "GormBaseModel",
    # fund
    "Fund",
    "FundWatchlistItem",
    "FundOpenRankLatest",
    "FundExchangeRankLatest",
    "FundMoneyRankLatest",
    "FundPerformanceTrendLatest",
    # user
    "User",
    "UserAIModelConfig",
    # rag
    "RagDocument",
    "RagChunk",
    "RagChunkEmbedding",
    "RagEvent",
    "RagWeeklyReport",
    "RagQueryLog",
    # news
    "NewsSource",
    "NewsRawItem",
    "NewsItem",
    "NewsItemTopic",
    "NewsItemEntity",
    "NewsItemRelation",
    # agent
    "PromptTemplate",
    "AgentThread",
    "AgentRun",
    "AgentMessage",
]
