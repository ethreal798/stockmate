"""RAG 检索服务。"""

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.rag import RagChunk, RagChunkEmbedding
from app.services.rag.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class RetrievalService:
    """RAG chunk 召回服务。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.embedding_service = EmbeddingService(db)

    async def retrieve(
        self,
        query: str,
        top_k: int = 8,
        days: int | None = 7,
    ) -> dict[str, Any]:
        """混合召回（BM25 + 向量）→ RRF 融合。"""
        embedding_model = settings.AI_EMBEDDING_MODEL

        # 1. BM25 关键词检索（pg_textsearch + zhparser）
        #    用 savepoint 隔离：炸了只回滚自己的 savepoint，不影响向量检索
        keyword_items: list[dict[str, Any]] = []
        sp_bm25 = await self.db.begin_nested()
        try:
            keyword_items = await self._keyword_retrieve(query=query, top_k=top_k, days=days)
            await sp_bm25.commit()
        except Exception as exc:
            logger.warning("BM25 retrieval failed: %s", exc)
            await sp_bm25.rollback()

        # 2. 向量检索（pgvector cosine_distance）
        sp_vec = await self.db.begin_nested()
        try:
            vector_items = await self._vector_retrieve(
                query=query,
                top_k=top_k,
                days=days,
                model=embedding_model,
            )
            await sp_vec.commit()
        except Exception as exc:
            logger.warning("Vector retrieval failed: %s", exc)
            await sp_vec.rollback()

        # 3. RRF 融合（k=60）— 只看排名，不看分数绝对值
        candidates = self._rrf_merge(keyword_items, vector_items)
        items = sorted(candidates.values(), key=lambda item: item["rrf_score"], reverse=True)[:top_k]

        return {
            "query": query,
            "top_k": top_k,
            "days": days,
            "model": embedding_model,
            "items": [self._format_item(item) for item in items],
        }

    async def _vector_retrieve(
        self,
        query: str,
        top_k: int,
        days: int | None,
        model: str,
    ) -> list[dict[str, Any]]:
        """pgvector cosine_distance 向量检索（保持原有逻辑不变）。"""
        query_vector = (await self.embedding_service.embed_texts([query], embedding_model=model))[0]
        distance = RagChunkEmbedding.embedding_vector.cosine_distance(query_vector).label("distance")
        join_condition = (
            RagChunkEmbedding.chunk_id == RagChunk.id,
            RagChunkEmbedding.embedding_model == model,
        )
        stmt = (
            select(RagChunk, distance)
            .join(RagChunkEmbedding, and_(*join_condition))
            .order_by(distance.asc())
            .limit(top_k * 3)
        )
        stmt = self._apply_time_filter(stmt, days)

        result = await self.db.execute(stmt)
        items: list[dict[str, Any]] = []
        for chunk, vector_distance in result.all():
            score = max(0.0, 1.0 - float(vector_distance or 0))
            items.append({"chunk": chunk, "score": score, "match_type": "vector"})
        return items

    async def _keyword_retrieve(self, query: str, top_k: int, days: int | None) -> list[dict[str, Any]]:
        """pg_textsearch BM25 关键词检索。

        zhparser 在 PG 层自动做中文分词，应用层不需要分词。
        <@> 运算符返回负数 BM25 分数，升序排（最相关的排最前面）。
        to_bm25query 第二个参数显式指定索引名。

        先用原生 SQL 拿到 chunk_id 排序列表，再用 ORM 查完整对象。
        """
        if not query.strip():
            return []

        # Python 层预处理 since —— None 时 SQL 里完全不放这个参数
        # 避免 PG 报 AmbiguousParameterError（NULL 无法推断类型）
        since = (datetime.now() - timedelta(days=days)) if days else None

        # 动态拼接 WHERE 条件
        # ⚠️ 索引名硬编码 'idx_chunks_bm25'，改名需同步改这里
        # <@> 返回负数，ORDER BY ASC 才对！
        # 不匹配行返回 0，需要 WHERE 过滤掉
        sql_parts = [
            "SELECT id, chunk_text <@> to_bm25query(:query, 'idx_chunks_bm25') AS bm25_rank",
            "FROM rag_chunks",
            "WHERE chunk_text <@> to_bm25query(:query, 'idx_chunks_bm25') < 0",
        ]
        params: dict[str, Any] = {"query": query.strip(), "limit": top_k * 3}

        if since is not None:
            sql_parts.append("AND (published_at >= :since OR published_at IS NULL)")
            params["since"] = since

        sql_parts.append("ORDER BY bm25_rank ASC")
        sql_parts.append("LIMIT :limit")

        result = await self.db.execute(text("\n".join(sql_parts)), params)

        # 拿到 chunk_id 列表
        rows = result.mappings().all()
        if not rows:
            return []

        chunk_ids = [row["id"] for row in rows]
        rank_by_id = {row["id"]: abs(float(row["bm25_rank"])) for row in rows}

        # 用 ORM 查完整 RagChunk 对象
        from sqlalchemy import select as sa_select

        chunks_result = await self.db.execute(sa_select(RagChunk).where(RagChunk.id.in_(chunk_ids)))
        chunk_map = {c.id: c for c in chunks_result.scalars().all()}

        # 按 BM25 排名顺序组装结果
        items: list[dict[str, Any]] = []
        for cid in chunk_ids:
            chunk = chunk_map.get(cid)
            if chunk is not None:
                items.append(
                    {
                        "chunk": chunk,
                        "score": rank_by_id[cid],
                        "match_type": "bm25",
                    }
                )
        return items

    @staticmethod
    def _rrf_merge(*item_lists: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        """Reciprocal Rank Fusion — 只看排名，不看分数绝对值。

        k=60 是业界标准值。同一 chunk 出现在多个通道时，
        match_type 用 '+' 拼接保留全部来源（如 "bm25+vector"）。
        """
        k = 60
        rrf_scores: dict[int, float] = {}
        combined_items: dict[int, dict[str, Any]] = {}
        seen_match_types: dict[int, set[str]] = {}

        for item_list in item_lists:
            # 每个通道内按原 score 降序排（排名在通道内有意义）
            ranked = sorted(item_list, key=lambda item: item["score"], reverse=True)
            for rank, item in enumerate(ranked, start=1):  # 1-based
                chunk_id = item["chunk"].id
                rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + 1.0 / (k + rank)

                # 保留所有命中来源的 match_type（不覆盖）
                if chunk_id not in combined_items:
                    combined_items[chunk_id] = item
                    seen_match_types[chunk_id] = {item["match_type"]}
                else:
                    seen_match_types[chunk_id].add(item["match_type"])

        # 把 RRF 分数和合并后的 match_type 写进去
        for chunk_id, types in seen_match_types.items():
            combined_items[chunk_id]["rrf_score"] = rrf_scores[chunk_id]
            combined_items[chunk_id]["match_type"] = "+".join(sorted(types))

        return combined_items

    @staticmethod
    def _apply_time_filter(stmt, days: int | None):
        """增加指定时间维度的筛选。"""
        if not days:
            return stmt
        since = datetime.now() - timedelta(days=days)
        return stmt.where(or_(RagChunk.published_at >= since, RagChunk.published_at.is_(None)))

    @staticmethod
    def _format_item(item: dict[str, Any]) -> dict[str, Any]:
        """将切片转化成可展示的 schema。"""
        chunk: RagChunk = item["chunk"]
        metadata = chunk.extra_metadata or {}
        return {
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "chunk_index": chunk.chunk_index,
            "title": metadata.get("document_title"),
            "content": chunk.chunk_text,
            "source_name": chunk.source_name,
            "url": metadata.get("document_url"),
            "published_at": chunk.published_at,
            "category": chunk.category,
            "sentiment": chunk.sentiment,
            "score": round(float(item.get("rrf_score", item["score"])), 6),
            "match_type": item["match_type"],
        }
