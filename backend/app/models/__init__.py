"""应用模型模块，导出所有 SQLAlchemy 模型和 Base。"""

from app.core.database import Base

from .base import TimestampMixin, SoftDeleteMixin, GormBaseModel
from .user import User
from .stock import (
    FollowedStock,
    StockBasic,
    AllStockInfo,
    StockInfoHK,
    StockInfoUS,
    StockGroup,
    StockGroupItem,
    StockInfo,
    IndexBasic,
    TradingRecord,
    BKDict,
)
from .rag import (
    RagDocument,
    RagChunk,
    RagChunkEmbedding,
    RagEvent,
    RagWeeklyReport,
    RagQueryLog,
)
from .news import NewsSource, NewsRawItem, NewsItem, NewsItemTopic, NewsItemEntity, NewsItemRelation
from .market import (
    MarketStatistic,
    StockChangeHistory,
    WordAnalyze,
    SentimentResultAnalyze,
    GlobalStockIndex,
    LongTigerRankData,
)
from .system import (
    Settings,
    CronTask,
    CronTaskExecutionLog,
    MCPServer,
    MCPServerTool,
    Skill,
    SkillConfig,
    AiAssistantSession,
    AIConfig,
    VersionInfo,
)
from .settings import UserAIModelConfig
from .agent import AgentMessage, AgentRun, AgentThread, PromptTemplate
from .strategy import CustomStrategy
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
    # stock
    "FollowedStock",
    "StockBasic",
    "AllStockInfo",
    "StockInfoHK",
    "StockInfoUS",
    "StockGroup",
    "StockGroupItem",
    "StockInfo",
    "IndexBasic",
    "TradingRecord",
    "BKDict",
    # ai
    "PromptTemplate",
    "RagDocument",
    "RagChunk",
    "RagChunkEmbedding",
    "RagEvent",
    "RagWeeklyReport",
    "RagQueryLog",
    # market
    "NewsSource",
    "NewsRawItem",
    "NewsItem",
    "NewsItemTopic",
    "NewsItemEntity",
    "NewsItemRelation",
    "MarketStatistic",
    "StockChangeHistory",
    "WordAnalyze",
    "SentimentResultAnalyze",
    "GlobalStockIndex",
    "LongTigerRankData",
    # system
    "Settings",
    "CronTask",
    "CronTaskExecutionLog",
    "MCPServer",
    "MCPServerTool",
    "Skill",
    "SkillConfig",
    "AiAssistantSession",
    "AIConfig",
    "VersionInfo",
    "UserAIModelConfig",
    "AgentThread",
    "AgentRun",
    "AgentMessage",
    # strategy
    "CustomStrategy",
]
