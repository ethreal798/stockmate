"""RAG 相关 Pydantic Schema。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RagDocumentResponse(BaseModel):
    """RAG 文档响应。"""

    id: int
    source_type: str
    source_id: int
    title: Optional[str] = None
    content: str
    content_hash: str
    published_at: Optional[datetime] = None
    source_name: Optional[str] = None
    url: Optional[str] = None
    category: Optional[str] = None
    importance_score: int = 0
    sentiment: Optional[str] = None
    language: str = "zh"
    status: str = "pending"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class RagChunkResponse(BaseModel):
    """RAG 分块响应。"""

    id: int
    document_id: int
    chunk_index: int
    chunk_text: str
    chunk_hash: str
    token_count: int = 0
    start_offset: int = 0
    end_offset: int = 0
    published_at: Optional[datetime] = None
    source_name: Optional[str] = None
    category: Optional[str] = None
    importance_score: int = 0
    sentiment: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class RagNewsIngestRequest(BaseModel):
    """新闻入库请求。"""

    limit: int = Field(100, ge=1, le=1000, description="本次最多处理多少条新闻")
    news_type: str = Field("all", description="新闻类型: all / fast / news")
    source_code: str = Field("all", description="来源类型：all / cls")


class RagNewsIngestResponse(BaseModel):
    """新闻入库响应。"""

    success: bool = True
    scanned: int = 0
    ingested: int = 0
    skipped_invalid: int = 0


class RagChunkRequest(BaseModel):
    """RAG 文档切块请求（FlashV1 策略，无需额外参数）。"""

    limit: int = Field(100, ge=1, le=1000, description="本次最多处理多少篇文档")


class RagChunkBatchResponse(BaseModel):
    """RAG 文档切块响应。"""

    success: bool = True
    scanned: int = 0
    chunked_documents: int = 0
    chunks_created: int = 0
    skipped_invalid: int = 0


class RagEmbedRequest(BaseModel):
    """RAG chunk 向量化请求。"""

    limit: int = Field(100, ge=1, le=1000, description="本次最多处理多少个 chunk")
    # model: Optional[str] = Field(None, description="Embedding 模型名称，默认使用配置项")


class RagEmbedResponse(BaseModel):
    """RAG chunk 向量化响应。"""

    success: bool = True
    scanned: int = 0
    embedded: int = 0
    skipped_existing: int = 0
    skipped_invalid: int = 0
    model: str
    embedding_dim: int


class RagNewsPipelineRequest(BaseModel):
    """新闻 RAG 一键流水线请求（FlashV1 切片，无需额外参数）。"""

    news_limit: int = Field(100, ge=1, le=1000, description="本次最多同步多少条新闻")
    news_type: str = Field("all", description="新闻类型: all / fast / news")
    relevant_only: bool = Field(True, description="是否仅处理金融相关资讯")
    chunk_limit: int = Field(100, ge=1, le=1000, description="本次最多切分多少篇文档")
    embed_limit: int = Field(100, ge=1, le=1000, description="本次最多向量化多少个 chunk")
    embedding_model: Optional[str] = Field(None, description="Embedding 模型名称，默认使用配置项")


class RagNewsPipelineDrainRequest(RagNewsPipelineRequest):
    """RAG 流水线受控排空请求。"""

    max_batches: int = Field(5, ge=1, le=20, description="本次最多排空多少个批次")
    max_seconds: int = Field(180, ge=10, le=900, description="本次最多运行多少秒")


class RagNewsPipelineResponse(BaseModel):
    """新闻 RAG 一键流水线响应。"""

    success: bool = True
    failed_stage: Optional[str] = None
    error: Optional[str] = None
    ingest: Optional[RagNewsIngestResponse] = None
    chunk: Optional[RagChunkBatchResponse] = None
    embed: Optional[RagEmbedResponse] = None


class RagNewsPipelineDrainResponse(BaseModel):
    """RAG 流水线受控排空响应。"""

    success: bool = True
    failed_stage: Optional[str] = None
    error: Optional[str] = None
    batch_count: int = 0
    stopped_reason: str = "idle"
    totals: dict[str, int] = Field(default_factory=dict)
    batches: list[RagNewsPipelineResponse] = Field(default_factory=list)


class RagRetrieveRequest(BaseModel):
    """RAG 检索请求。"""

    query: str = Field(..., min_length=1, description="用户查询")
    top_k: int = Field(8, ge=1, le=50, description="返回 chunk 数量")
    days: Optional[int] = Field(7, ge=1, le=365, description="检索最近多少天的数据")
    # model: Optional[str] = Field(None, description="Embedding 模型名称，默认使用配置项")
    # use_vector: bool = Field(True, description="是否启用向量召回")


class RagRetrieveItem(BaseModel):
    """RAG 检索结果项。"""

    chunk_id: int
    document_id: int
    chunk_index: int
    title: Optional[str] = None
    content: str
    source_name: Optional[str] = None
    url: Optional[str] = None
    published_at: Optional[datetime] = None
    category: Optional[str] = None
    sentiment: Optional[str] = None
    score: float
    match_type: str


class RagRetrieveResponse(BaseModel):
    """RAG 检索响应。"""

    query: str
    top_k: int
    days: Optional[int] = None
    model: str
    items: list[RagRetrieveItem] = Field(default_factory=list)


class RagCitation(BaseModel):
    """RAG 回答引用来源。"""

    index: int
    chunk_id: int
    document_id: int
    title: Optional[str] = None
    source_name: Optional[str] = None
    url: Optional[str] = None
    published_at: Optional[datetime] = None
    score: Optional[float] = None
    match_type: Optional[str] = None


class RagChatRequest(BaseModel):
    """RAG 问答请求。"""

    message: str = Field(..., min_length=1, description="用户问题")
    conversation_id: Optional[str] = Field(None, description="会话ID，为空则新建")
    top_k: int = Field(8, ge=1, le=50, description="用于回答的召回 chunk 数")
    days: Optional[int] = Field(7, ge=1, le=365, description="检索最近多少天的数据")
    model: Optional[str] = Field(None, description="回答模型名称")


class RagChatResponse(BaseModel):
    """RAG 问答响应。"""

    conversation_id: str
    answer: str
    citations: list[RagCitation] = Field(default_factory=list)
    retrieved_count: int = 0
    model: str
    usage: Optional[dict] = None
