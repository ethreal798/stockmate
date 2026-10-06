"""新闻爬取定时任务。"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.config import settings
from app.services.news_service import NewsService
from app.services.rag.rag_pipeline_service import RagPipelineService
from app.services.scheduler.task_registry import register_task

logger = logging.getLogger(__name__)

# RAG 流水线执行锁，防止并发重复运行
_rag_pipeline_lock = asyncio.Lock()
_last_rag_pipeline_run_at = 0.0


async def _execute_news_crawl(db, params: dict[str, Any]) -> int:
    """执行新闻爬取，返回新增条数。"""
    service = NewsService(db)
    source = params.get("source", "all")

    if source == "all":
        results = await service.fetch_all_sources()
        total_new_count = sum(results.values())
        log = logger.info if total_new_count > 0 else logger.debug
        log("News crawl completed: source=all, total_new_count=%s, results=%s", total_new_count, results)
        return total_new_count

    news_type = params.get("type", "flash")
    total_new_count = await service.fetch_remote_news(source, source_type=news_type)
    log = logger.info if total_new_count > 0 else logger.debug
    log("News crawl completed: source=%s, total_new_count=%s", source, total_new_count)
    return total_new_count


async def _run_rag_pipeline_drain(
    db,
    params: dict[str, Any],
    *,
    reason: str,
    total_new_count: int | None = None,
) -> None:
    """执行 RAG 流水线 drain 操作。"""
    global _last_rag_pipeline_run_at

    if _rag_pipeline_lock.locked():
        logger.debug("Skip RAG pipeline: previous pipeline is still running, reason=%s", reason)
        return

    now = time.monotonic()
    elapsed = now - _last_rag_pipeline_run_at
    if elapsed < settings.RAG_PIPELINE_MIN_INTERVAL_SECONDS:
        logger.debug(
            "Skip RAG pipeline: min interval not reached, reason=%s, elapsed=%.2fs, required=%ss",
            reason,
            elapsed,
            settings.RAG_PIPELINE_MIN_INTERVAL_SECONDS,
        )
        return

    async with _rag_pipeline_lock:
        _last_rag_pipeline_run_at = time.monotonic()
        pipeline_service = RagPipelineService(db)
        result = await pipeline_service.run_news_pipeline_drain(
            max_batches=params.get("rag_drain_max_batches", settings.RAG_PIPELINE_DRAIN_MAX_BATCHES),
            max_seconds=params.get("rag_drain_max_seconds", settings.RAG_PIPELINE_DRAIN_MAX_SECONDS),
            news_limit=params.get("rag_news_limit", settings.RAG_PIPELINE_NEWS_LIMIT),
            news_type=params.get("rag_news_type", "all"),
            relevant_only=params.get("rag_relevant_only", True),
            chunk_limit=params.get("rag_chunk_limit", settings.RAG_PIPELINE_CHUNK_LIMIT),
            embed_limit=params.get("rag_embed_limit", settings.RAG_PIPELINE_EMBED_LIMIT),
            embedding_model=params.get("rag_embedding_model"),
        )

        if result["success"]:
            logger.info(
                "RAG pipeline completed: reason=%s, total_new_count=%s, result=%s",
                reason,
                total_new_count,
                result,
            )
        else:
            logger.warning(
                "RAG pipeline failed: reason=%s, total_new_count=%s, failed_stage=%s, error=%s, result=%s",
                reason,
                total_new_count,
                result["failed_stage"],
                result["error"],
                result,
            )


@register_task(
    task_id="news_crawl",
    trigger_config_key="NEWS_CRAWL_INTERVAL_SECONDS",
    enabled_key="NEWS_CRAWL_INTERVAL_SECONDS",  # 间隔 > 0 即启用
)
async def news_crawl(db, params: dict[str, Any]) -> None:
    """新闻爬取定时任务。

    爬取完成后，若有新增新闻且 RAG 流水线已开启，
    将自动触发一次 RAG 流水线 drain。
    """
    total_new_count = await _execute_news_crawl(db, params)

    if total_new_count > 0 and settings.RAG_PIPELINE_SWITCH and settings.RAG_PIPELINE_ON_NEWS_CRAWL:
        await _run_rag_pipeline_drain(db, params, reason="news_crawl", total_new_count=total_new_count)
