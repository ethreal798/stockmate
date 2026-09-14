"""统一资讯主表进入 RAG 文档表的服务。"""

import hashlib
from datetime import timezone
from typing import Any

from sqlalchemy import Select, and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.news import NewsItem, NewsSource
from app.models.rag import RagDocument


class NewsIngestService:
    """将尚未同步的 NewsItem 写入 RAG 文档表。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def ingest_telegraphs(
        self, limit: int = 100, news_type: str = "all", source_code: str = "all",
    ) -> dict[str, int]:
        """ 加载文档：支持指定数据类型及来源 """
        # 1. 构建查询语句 详见 _build_news_query
        stmt = self._build_news_query(limit=limit, news_type=news_type, source_code=source_code)
        # 2. 执行查询 并去重
        result = await self.db.execute(stmt)
        news_items = list(result.scalars().unique().all())

        # 3. 文档入库
        stats = {"scanned": len(news_items), "ingested": 0, "skipped_invalid": 0}
        for item in news_items:
            if not item.content or not item.content.strip():
                stats["skipped_invalid"] += 1
                continue
            self.db.add(self._build_document(item))
            stats["ingested"] += 1

        if stats["ingested"]:
            await self.db.commit()
        return stats

    async def list_documents(self, limit: int = 20) -> list[RagDocument]:
        """ 返回RAG文档库中的文档 按limit指定数量 """
        result = await self.db.execute(select(RagDocument).order_by(desc(RagDocument.created_at)).limit(limit))
        return list(result.scalars().all())

    @staticmethod
    def _build_news_query(limit: int, news_type: str, source_code: str) -> Select[tuple[NewsItem]]:
        # 1. 将资讯对应的关联信息一并构建 等待后续执行SQL查出对应数据
        stmt = select(NewsItem).options(
            selectinload(NewsItem.source),
            selectinload(NewsItem.topics),
            selectinload(NewsItem.entities),
            selectinload(NewsItem.relations),
        )
        stmt = stmt.join(NewsSource)

        # 2. 资讯题材过滤
        normalized_type = {"fast": "flash", "news": "article"}.get(news_type, news_type)
        if normalized_type != "all":
            stmt = stmt.where(NewsItem.content_type == normalized_type)

        # 3. 来源过滤
        if source_code != "all":
            stmt = stmt.where(NewsItem.source.code == source_code)

        # 4. 过滤已加载 根据文档表已有的来源id进行过滤 RagDocument.source_id == NewsItem.id
        existing_document = (
            select(RagDocument.source_id)
            .where(
                and_(
                    RagDocument.source_type == NewsItem.content_type,
                    RagDocument.source_id == NewsItem.id,
                )
            )
            .exists()
        )
        return (
            stmt.where(~existing_document, NewsItem.content.is_not(None), NewsItem.content != "")
            .order_by(desc(NewsItem.published_at), desc(NewsItem.id))
            .limit(limit)
        )

    def _build_document(self, item: NewsItem) -> RagDocument:
        """ 文档入库：将资讯转换为RAG文档表格式 """
        content = item.content.strip()

        return RagDocument(
            source_type=item.content_type,
            source_id=item.id,
            title=(item.title or "").strip() or None,
            content=content,
            content_hash=self._hash_text(content),
            published_at=self._rag_datetime(item.published_at),
            source_name=item.source.name,
            url=self._original_document_url(item),
            category=None,
            importance_score=100 if item.is_source_important else 0,
            sentiment=None,
            language="zh",
            status="pending",
            extra_metadata=self._build_metadata(item),
        )

    @staticmethod
    def _build_metadata(item: NewsItem) -> dict[str, Any]:
        """ 将资讯关联的数据打包进extra_metadata字段中 （目前未使用，但后续可能使用先保留）"""
        return {
            "source_code": item.source.code,
            "is_source_important": bool(item.is_source_important),
            "topics": [topic.name for topic in item.topics],
            "entities": [
                {
                    "type": entity.entity_type,
                    "name": entity.name,
                    "symbol": entity.symbol,
                }
                for entity in item.entities
            ],
        }

    @staticmethod
    def _hash_text(text: str) -> str:
        """ 对内容进行哈希计算 用于去重  """
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _original_document_url(item: NewsItem) -> str | None:
        """ 提取资讯相关来源 """
        return next((relation.url for relation in item.relations if relation.url), None)

    @staticmethod
    def _rag_datetime(value):
        """旧 RAG 时间列不带时区，统一写入 UTC naive 值。"""
        if value is None or value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)
