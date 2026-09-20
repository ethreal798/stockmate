"""AI RAG 路由。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.rag import (
    RagChatRequest,
    RagChatResponse,
    RagChunkBatchResponse,
    RagChunkRequest,
    RagChunkResponse,
    RagDocumentResponse,
    RagEmbedRequest,
    RagEmbedResponse,
    RagNewsIngestRequest,
    RagNewsIngestResponse,
    RagNewsPipelineDrainRequest,
    RagNewsPipelineDrainResponse,
    RagNewsPipelineResponse,
    RagRetrieveRequest,
    RagRetrieveResponse,
)
from app.services.rag.chunk_service import ChunkService
from app.services.rag.embedding_service import EmbeddingService
from app.services.rag.news_ingest_service import NewsIngestService
from app.services.rag.rag_pipeline_service import RagPipelineService
from app.services.rag.rag_service import RagService
from app.services.rag.retrieval_service import RetrievalService

router = APIRouter(prefix="/ai/rag", tags=["ai-rag"])


def get_news_ingest_service(db: AsyncSession = Depends(get_db)) -> NewsIngestService:
    return NewsIngestService(db)


def get_chunk_service(db: AsyncSession = Depends(get_db)) -> ChunkService:
    return ChunkService(db)


def get_embedding_service(db: AsyncSession = Depends(get_db)) -> EmbeddingService:
    return EmbeddingService(db)


def get_retrieval_service(db: AsyncSession = Depends(get_db)) -> RetrievalService:
    return RetrievalService(db)


def get_rag_service(db: AsyncSession = Depends(get_db)) -> RagService:
    return RagService(db)


def get_rag_pipeline_service(db: AsyncSession = Depends(get_db)) -> RagPipelineService:
    return RagPipelineService(db)


def build_pipeline_response(result: dict) -> RagNewsPipelineResponse:
    ingest = (
        RagNewsIngestResponse(success=result["failed_stage"] != "ingest", **result["ingest"])
        if result["ingest"]
        else None
    )
    chunk = (
        RagChunkBatchResponse(success=result["failed_stage"] != "chunk", **result["chunk"]) if result["chunk"] else None
    )
    embed = RagEmbedResponse(success=result["failed_stage"] != "embed", **result["embed"]) if result["embed"] else None

    return RagNewsPipelineResponse(
        success=result["success"],
        failed_stage=result["failed_stage"],
        error=result["error"],
        ingest=ingest,
        chunk=chunk,
        embed=embed,
    )


@router.post("/ingest/news", response_model=RagNewsIngestResponse, summary="将新闻同步到 RAG 文档表")
async def ingest_news(
    request: RagNewsIngestRequest,
    service: NewsIngestService = Depends(get_news_ingest_service),
) -> RagNewsIngestResponse:
    stats = await service.ingest_telegraphs(
        limit=request.limit,
        news_type=request.news_type,
        source_code=request.source_code,
    )
    return RagNewsIngestResponse(success=True, **stats)


@router.get("/documents", response_model=list[RagDocumentResponse], summary="查看最新 RAG 文档")
async def list_documents(
    limit: int = Query(20, ge=1, le=100),
    service: NewsIngestService = Depends(get_news_ingest_service),
) -> list[RagDocumentResponse]:
    documents = await service.list_documents(limit=limit)
    return [RagDocumentResponse.model_validate(document) for document in documents]


@router.post("/chunk", response_model=RagChunkBatchResponse, summary="将 RAG 文档切分为 chunk")
async def chunk_documents(
    request: RagChunkRequest,
    service: ChunkService = Depends(get_chunk_service),
) -> RagChunkBatchResponse:
    stats = await service.chunk_pending_documents(
        limit=request.limit,
    )
    return RagChunkBatchResponse(success=True, **stats)


@router.get("/chunks", response_model=list[RagChunkResponse], summary="查看最新 RAG chunk")
async def list_chunks(
    limit: int = Query(20, ge=1, le=100),
    service: ChunkService = Depends(get_chunk_service),
) -> list[RagChunkResponse]:
    chunks = await service.list_chunks(limit=limit)
    return [RagChunkResponse.model_validate(chunk) for chunk in chunks]


@router.post("/embed", response_model=RagEmbedResponse, summary="将 RAG chunk 向量化")
async def embed_chunks(
    request: RagEmbedRequest,
    service: EmbeddingService = Depends(get_embedding_service),
) -> RagEmbedResponse:
    stats = await service.embed_pending_chunks(limit=request.limit, model=request.model)
    return RagEmbedResponse(success=True, **stats)


@router.post("/pipeline/news/drain", response_model=RagNewsPipelineDrainResponse, summary="受控排空新闻 RAG 流水线")
async def run_news_pipeline_drain(
    request: RagNewsPipelineDrainRequest,
    service: RagPipelineService = Depends(get_rag_pipeline_service),
) -> RagNewsPipelineDrainResponse:
    result = await service.run_news_pipeline_drain(
        max_batches=request.max_batches,
        max_seconds=request.max_seconds,
        news_limit=request.news_limit,
        news_type=request.news_type,
        relevant_only=request.relevant_only,
        chunk_limit=request.chunk_limit,
        embed_limit=request.embed_limit,
        embedding_model=request.embedding_model,
    )

    return RagNewsPipelineDrainResponse(
        success=result["success"],
        failed_stage=result["failed_stage"],
        error=result["error"],
        batch_count=result["batch_count"],
        stopped_reason=result["stopped_reason"],
        totals=result["totals"],
        batches=[build_pipeline_response(batch) for batch in result["batches"]],
    )


@router.post("/retrieve", response_model=RagRetrieveResponse, summary="检索 RAG chunk")
async def retrieve_chunks(
    request: RagRetrieveRequest,
    service: RetrievalService = Depends(get_retrieval_service),
) -> RagRetrieveResponse:
    result = await service.retrieve(
        query=request.query,
        top_k=request.top_k,
        days=request.days,
    )
    return RagRetrieveResponse.model_validate(result)


@router.post("/chat", response_model=RagChatResponse, summary="RAG 新闻问答")
async def chat(
    request: RagChatRequest,
    service: RagService = Depends(get_rag_service),
) -> RagChatResponse:
    result = await service.answer(
        message=request.message,
        conversation_id=request.conversation_id,
        top_k=request.top_k,
        days=request.days,
        model=request.model,
    )
    return RagChatResponse.model_validate(result)
