"""RAG chunk 向量化服务。"""

import asyncio
import logging

import httpx
from sqlalchemy import and_, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.rag import RagChunk, RagChunkEmbedding, RagDocument

logger = logging.getLogger(__name__)


class EmbeddingService:
    """调用 OpenAI 兼容接口生成 embedding 并写入 pgvector。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def embed_pending_chunks(self, limit: int = 100, model: str | None = None) -> dict[str, int | str]:
        """向量化尚未使用指定模型处理过的 chunk。

        优先读取 chunk.embedding_text（FlashV1 切片时生成），fallback 到 chunk.chunk_text。
        batch 失败不阻断后续处理，成功后批量更新 document.processing_stage='embedded'。
        """
        # 1. 获取指定向量化模型
        embedding_model = model or settings.AI_EMBEDDING_MODEL
        # 2. 取未被向量化的chunk
        chunks = await self._get_chunks_without_embedding(limit=limit, model=embedding_model)
        stats: dict[str, int | str] = {
            "scanned": len(chunks),
            "embedded": 0,
            "batch_failed": 0,
            "skipped_invalid": 0,
            "model": embedding_model,
            "embedding_dim": settings.AI_EMBEDDING_DIM,
        }

        if not chunks:
            return stats

        batch_size = max(1, settings.AI_EMBEDDING_BATCH_SIZE)
        embedded_document_ids: set[int] = set()

        # 3. 遍历所有批次，依次对每批的chunk完成向量化
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            valid_pairs: list[tuple[RagChunk, str]] = []
            inputs = []
            # 3.1 遍历每批的chunk 将chunk的待向量化文本存入valid_pairs,inputs中
            for chunk in batch:
                text = chunk.embedding_text
                if text and text.strip():
                    valid_pairs.append((chunk, text.strip()))
                    inputs.append(text.strip())
                else:
                    stats["skipped_invalid"] = int(stats["skipped_invalid"]) + 1

            if not valid_pairs:
                continue

            # 3.2 向量化文本
            try:
                vectors = await self.embed_texts(inputs, embedding_model=embedding_model)
            except Exception as exc:
                # batch 级失败隔离：记录日志，跳过本 batch，下次 pipeline 重跑时重试
                logger.error("Embedding batch failed (%d chunks): %s", len(valid_pairs), exc)
                stats["batch_failed"] = int(stats["batch_failed"]) + 1
                continue

            # 3.3 文本向量结果入库
            for (chunk, _), vector in zip(valid_pairs, vectors):
                self.db.add(
                    RagChunkEmbedding(
                        chunk_id=chunk.id,
                        embedding_model=embedding_model,
                        embedding_dim=len(vector),
                        embedding_vector=vector,
                    )
                )
                stats["embedded"] = int(stats["embedded"]) + 1
                embedded_document_ids.add(chunk.document_id)

            await self.db.commit()

        # 批量更新已完成向量化的 document 的 processing_stage
        # 注意：只更新所有 flash-v1 chunk 都已向量化的 document，
        # 避免 batch 间部分 chunk 成功、部分失败时误标记
        if embedded_document_ids:
            fully_embedded_ids = await self._filter_fully_embedded_documents(embedded_document_ids, embedding_model)
            if fully_embedded_ids:
                await self._update_document_stage(fully_embedded_ids, "embedded")

        return stats

    # 调用Embedding模型进行向量化
    async def embed_texts(self, texts: list[str], embedding_model: str) -> list[list[float]]:
        """调用 OpenAI 兼容 /embeddings 接口。"""
        if not texts:
            return []

        payload = {"model": embedding_model, "input": texts}
        # 1. 设置向量维度信息
        if settings.AI_EMBEDDING_REQUEST_DIMENSIONS > 0:
            payload["dimensions"] = settings.AI_EMBEDDING_REQUEST_DIMENSIONS

        # 2. 准备请求头
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {settings.AI_EMBEDDING_API_KEY}"}

        # 3. 拼接服务商提供的url，发送向量化文本请求
        url = f"{settings.AI_EMBEDDING_BASE_URL.rstrip('/')}/embeddings"
        async with httpx.AsyncClient(timeout=float(settings.AI_EMBEDDING_TIMEOUT_SECONDS)) as client:
            response = await self._post_with_retry(client, url, payload, headers)

        # 4. 解析响应结果并返回
        data = response.json()
        vectors = [item["embedding"] for item in sorted(data.get("data", []), key=lambda item: item.get("index", 0))]
        # 5. 校验响应向量是否合理
        self._validate_vectors(vectors, expected_count=len(texts))
        return vectors

    async def _post_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        payload: dict,
        headers: dict[str, str],
    ) -> httpx.Response:
        """实际调用服务方 embedding模型 支持重试机制仅针对特定状态码"""
        retryable_status_codes = {408, 409, 425, 429, 500, 502, 503, 504}
        max_retries = max(0, settings.AI_EMBEDDING_MAX_RETRIES)

        for attempt in range(max_retries + 1):
            try:
                response = await client.post(url, json=payload, headers=headers)
                # 1. 响应状态码不在指定范围中
                if response.status_code not in retryable_status_codes:
                    self._raise_for_embedding_error(response, url)
                    return response

                # 2. 重试次数到达最大次数 仍失败
                if attempt >= max_retries:
                    self._raise_for_embedding_error(response, url)
                    return response

                # 3. 重试之前先等待一段时间
                await asyncio.sleep(self._retry_delay_seconds(response, attempt))
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError):
                # 如果捕获其他错误 继续重试直到耗尽最大重试次数
                if attempt >= max_retries:
                    raise
                await asyncio.sleep(self._retry_delay_seconds(None, attempt))

        raise RuntimeError("Embedding request retry loop exited unexpectedly")

    # 过滤已向量化的切片文档
    async def _get_chunks_without_embedding(self, limit: int, model: str) -> list[RagChunk]:
        """
        SELECT rag_chunk.*
        FROM rag_chunk
        LEFT OUTER JOIN rag_chunk_embedding
            ON rag_chunk_embedding.chunk_id = rag_chunk.id
            AND rag_chunk_embedding.embedding_model = :model
        WHERE rag_chunk_embedding.id IS NULL
            AND rag_chunk.chunking_version = 'flash-v1'
        ORDER BY rag_chunk.published_at DESC, rag_chunk.id DESC
        LIMIT :limit;
        """
        join_condition = and_(
            RagChunkEmbedding.chunk_id == RagChunk.id,
            RagChunkEmbedding.embedding_model == model,
        )
        stmt = (
            select(RagChunk)
            .outerjoin(RagChunkEmbedding, join_condition)
            .where(RagChunkEmbedding.id.is_(None))
            .where(RagChunk.chunking_version == "flash-v1")
            .order_by(desc(RagChunk.published_at), desc(RagChunk.id))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _filter_fully_embedded_documents(
        self,
        document_ids: set[int],
        model: str,
    ) -> set[int]:
        """只保留所有 flash-v1 chunk 都已用指定模型向量化的 document_id。"""
        if not document_ids:
            return set()

        join_cond = and_(
            RagChunkEmbedding.chunk_id == RagChunk.id,
            RagChunkEmbedding.embedding_model == model,
        )
        # EXISTS 子查询：document 下是否还有 flash-v1 chunk 没有该模型的 embedding
        unembedded_exists = (
            select(RagChunk.id)
            .outerjoin(RagChunkEmbedding, join_cond)
            .where(RagChunk.document_id == RagDocument.id)
            .where(RagChunk.chunking_version == "flash-v1")
            .where(RagChunkEmbedding.id.is_(None))
            .correlate(RagDocument)
            .exists()
        )
        stmt = select(RagDocument.id).where(RagDocument.id.in_(list(document_ids))).where(~unembedded_exists)
        result = await self.db.execute(stmt)
        return set(result.scalars().all())

    async def _update_document_stage(self, document_ids: set[int], stage: str) -> None:
        """批量更新已完成向量化的 document 的 processing_stage。"""
        stmt = update(RagDocument).where(RagDocument.id.in_(list(document_ids))).values(processing_stage=stage)
        await self.db.execute(stmt)
        await self.db.commit()

    @staticmethod
    def _raise_for_embedding_error(response: httpx.Response, url: str) -> None:
        """抛出错误给上游 并记录错误日志"""
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = response.text[:1000]
            raise httpx.HTTPStatusError(
                f"{exc}. Provider response body: {body}. Request URL: {url}",
                request=exc.request,
                response=exc.response,
            ) from exc

    @staticmethod
    def _retry_delay_seconds(response: httpx.Response | None, attempt: int) -> float:
        """优先尊重服务端指示等待时间，否则用指数退避"""
        retry_after = response.headers.get("Retry-After") if response is not None else None
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                logger.warning("Ignore unsupported Retry-After header: %s", retry_after)

        return settings.AI_EMBEDDING_RETRY_BASE_SECONDS * (2**attempt)

    @staticmethod
    def _validate_vectors(vectors: list[list[float]], expected_count: int) -> None:
        """初步校验服务商返回的响应结果 是否合理 1.数量 2.向量维度"""
        if len(vectors) != expected_count:
            raise ValueError(f"Embedding result count mismatch: expected {expected_count}, got {len(vectors)}")

        for index, vector in enumerate(vectors):
            if len(vector) != settings.AI_EMBEDDING_DIM:
                raise ValueError(
                    f"Embedding dimension mismatch at index {index}: "
                    f"expected {settings.AI_EMBEDDING_DIM}, got {len(vector)}"
                )
