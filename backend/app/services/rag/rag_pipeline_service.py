"""RAG pipeline orchestration service."""

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rag.chunk_service import ChunkService
from app.services.rag.embedding_service import EmbeddingService
from app.services.rag.news_ingest_service import NewsIngestService


class RagPipelineService:
    """Run RAG ingestion stages in order while preserving per-stage stats."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.news_ingest_service = NewsIngestService(db)
        self.chunk_service = ChunkService(db)
        self.embedding_service = EmbeddingService(db)

    # 流水线入口
    async def run_news_pipeline_drain(
        self,
        *,
        max_batches: int = 5,
        max_seconds: int = 180,
        news_limit: int = 100,
        news_type: str = "all",
        relevant_only: bool = True,
        chunk_limit: int = 100,
        embed_limit: int = 100,
        embedding_model: str | None = None,
    ) -> dict[str, Any]:
        started_at = time.monotonic()
        batches: list[dict[str, Any]] = []
        totals: dict[str, int] = {}
        stopped_reason = "idle"

        # 根据批次运行流水线作业
        for _ in range(max(1, max_batches)):
            # 1. 超时判断
            if time.monotonic() - started_at >= max_seconds:
                stopped_reason = "max_seconds"
                break

            # 2. 调用接口执行 入库 -> 切片 -> 向量化
            batch_result = await self.run_news_pipeline(
                news_limit=news_limit,
                news_type=news_type,
                chunk_limit=chunk_limit,
                embed_limit=embed_limit,
                embedding_model=embedding_model,
            )
            # 3. 统计结果
            batches.append(batch_result)
            self._accumulate_totals(totals, batch_result)

            # 4. 任一环节出错均结束流水线作业
            if not batch_result["success"]:
                return {
                    "success": False,
                    "failed_stage": batch_result["failed_stage"],
                    "error": batch_result["error"],
                    "batch_count": len(batches),
                    "stopped_reason": "failed",
                    "totals": totals,
                    "batches": batches,
                }
            # 5. 任一环节均成功但成功结果数为0 直接跳出结束流水线作业
            if not self._has_progress(batch_result):
                stopped_reason = "idle"
                break
        else:
            stopped_reason = "max_batches"

        return {
            "success": True,
            "failed_stage": None,
            "error": None,
            "batch_count": len(batches),
            "stopped_reason": stopped_reason,
            "totals": totals,
            "batches": batches,
        }

    # 实际执行 入库 -> 切片 -> 向量化操作
    async def run_news_pipeline(
        self,
        *,
        news_limit: int = 100,
        news_type: str = "all",
        chunk_limit: int = 100,
        embed_limit: int = 100,
        embedding_model: str | None = None,
    ) -> dict[str, Any]:
        # 组装返回结果
        result: dict[str, Any] = {
            "success": False,
            "failed_stage": None,
            "error": None,
            "ingest": None,
            "chunk": None,
            "embed": None,
        }

        # 1. 同步资讯进RAG文档表
        try:
            result["ingest"] = await self.news_ingest_service.ingest_telegraphs(
                limit=news_limit,
                news_type=news_type,
            )
        except Exception as exc:
            await self.db.rollback()
            return self._mark_failed(result, "ingest", exc)

        # 2. 对RAG文档表的文档进行文档切分
        try:
            result["chunk"] = await self.chunk_service.chunk_pending_documents(
                limit=chunk_limit,
            )
        except Exception as exc:
            await self.db.rollback()
            return self._mark_failed(result, "chunk", exc)

        # 3. 对切分好的chunk进行向量化
        try:
            result["embed"] = await self.embedding_service.embed_pending_chunks(
                limit=embed_limit,
                model=embedding_model,
            )
        except Exception as exc:
            await self.db.rollback()
            return self._mark_failed(result, "embed", exc)

        result["success"] = True
        return result

    @staticmethod
    def _mark_failed(result: dict[str, Any], stage: str, exc: Exception) -> dict[str, Any]:
        result["failed_stage"] = stage
        result["error"] = str(exc)
        return result

    @staticmethod
    def _has_progress(result: dict[str, Any]) -> bool:
        """ 判断本次作业结果是否成功 """
        ingest = result.get("ingest") or {}
        chunk = result.get("chunk") or {}
        embed = result.get("embed") or {}
        progressed = (
            int(ingest.get("ingested", 0))
            + int(chunk.get("chunked_documents", 0))
            + int(chunk.get("chunks_created", 0))
            + int(chunk.get("skipped_existing", 0))
            + int(chunk.get("skipped_invalid", 0))
            + int(embed.get("embedded", 0))
        )
        return progressed > 0

    @staticmethod
    def _accumulate_totals(totals: dict[str, int], result: dict[str, Any]) -> None:
        """ 计算三阶段的执行结果 """
        for stage in ("ingest", "chunk", "embed"):
            stats = result.get(stage) or {}
            for key, value in stats.items():
                if isinstance(value, int):
                    totals[f"{stage}_{key}"] = totals.get(f"{stage}_{key}", 0) + value
