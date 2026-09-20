"""RAG 文档切块服务 —— FlashV1 策略。

FlashV1 核心逻辑（基于财联社 17968 条实证定稿）：
  检测到 ≥2 个编号分点（正则：^\\s*[1-9][\\.、）]）→ 按编号分点切分
  否则 → 无论多长（100 字 or 1500 字）→ 整块保留

与旧版滑动窗口（max_chars=800, overlap=120）的区别：
  - 旧版按字符长度硬切，误伤 87.7% 单事件长文
  - 新版按语义分点切，仅对多事件汇总类（1.16%）切分
"""

import hashlib
import re

from sqlalchemy import Select, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rag import RagChunk, RagDocument

# FlashV1 编号分点正则：匹配行首的 "1." / "2、" / "9、" / "10、" 等编号格式
_NUMBERED_POINT_PATTERN = re.compile(r"^\s*\d+[\.、）]")


class ChunkService:
    """将 RAG 文档按 FlashV1 策略切分为可检索的 chunk。"""

    chunking_version = "flash-v1"

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def chunk_pending_documents(self, limit: int = 100) -> dict[str, int]:
        """切分 status='pending' 的 RAG 文档。

        流程结束后 document.status → 'chunked'，供 pipeline 控制流使用。
        """
        # 1. 准备未切分的文档
        stmt = self._build_pending_documents_query(limit=limit)
        result = await self.db.execute(stmt)
        documents = result.scalars().all()

        # 2. 本次切分结果汇总
        stats: dict[str, int] = {
            "scanned": len(documents),
            "chunked_documents": 0,
            "chunks_created": 0,
            "skipped_invalid": 0,
        }

        # 3. 遍历每条文档
        for document in documents:
            # 3.1 按制定的v1策略进行切片
            chunks = self.split_document_text_flash_v1(document)
            # 3.2 chunk为空则跳过
            if not chunks:
                document.status = "chunk_failed"
                document.processing_stage = "chunk_failed"
                document.processing_error = "正文为空"
                stats["skipped_invalid"] += 1
                continue

            # 3.3 遍历chunks 将chunk存入chunk表
            for index, chunk_data in enumerate(chunks):
                self.db.add(self._build_chunk(document, index, chunk_data))

            document.status = "chunked"
            stats["chunked_documents"] += 1
            stats["chunks_created"] += len(chunks)

        # 4. 完成一批后 直接提交事务。保证 Stage 之间的工作不互相影响
        if stats["chunked_documents"] > 0 or stats["skipped_invalid"] > 0:
            await self.db.commit()

        return stats

    async def list_chunks(self, limit: int = 20) -> list[RagChunk]:
        """列出最新的 RAG 分块。"""
        stmt = select(RagChunk).order_by(desc(RagChunk.created_at)).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    def split_document_text_flash_v1(self, document: RagDocument) -> list[dict[str, int | str]]:
        """FlashV1 切片主入口：检测编号分点 → 按分点切，否则整块。"""
        # 1. 内容为空直接跳过并返回空列表
        text = (document.content or "").strip()
        if not text:
            return []

        # 2. 判断是否为聚合摘要类资讯 按照换行符分割 并进行正则匹配
        lines = text.split("\n")
        numbered_indices = [i for i, line in enumerate(lines) if _NUMBERED_POINT_PATTERN.match(line)]

        if len(numbered_indices) >= 2:
            return self._split_by_numbered_points(lines, numbered_indices)
        else:
            # 整块保留，无论多长
            return [{"text": text, "start": 0, "end": len(text)}]

    def _split_by_numbered_points(
        self,
        lines: list[str],
        numbered_indices: list[int],
    ) -> list[dict[str, int | str]]:
        """按编号分点切分文本行。

        处理逻辑：
        1. 第一个编号之前如果有前置内容（标题/引言），丢弃
        2. 每个编号点到下一个编号点（或末尾）为一个 chunk
        """
        chunks: list[dict[str, int | str]] = []

        # 按编号点进行切分  使用chunks保存每个切分的一个小chunk
        for i, start_line in enumerate(numbered_indices):
            end_line = numbered_indices[i + 1] if i + 1 < len(numbered_indices) else len(lines)
            # 只去掉匹配到编号点的那一行的编号前缀，其他行原样保留
            chunk_lines = lines[start_line:end_line]
            chunk_lines[0] = _NUMBERED_POINT_PATTERN.sub("", chunk_lines[0], count=1).strip()
            chunk_text = "\n".join(chunk_lines).strip()
            if chunk_text:
                chunks.append(self._make_chunk_data(chunk_text))

        return chunks

    @staticmethod
    def _make_chunk_data(text: str) -> dict[str, int | str]:
        """构造 chunk 数据字典，start/end 占位。"""
        return {"text": text, "start": 0, "end": len(text)}

    @staticmethod
    def _build_pending_documents_query(limit: int) -> Select[tuple[RagDocument]]:
        """取未切分的文档 按limit取对应条数"""
        # LEFT JOIN rag_chunks 过滤掉已切片的文档，一次查询搞定
        return (
            select(RagDocument)
            .outerjoin(RagChunk, RagChunk.document_id == RagDocument.id)
            .where(RagDocument.status == "pending")
            .where(RagChunk.id.is_(None))
            .order_by(desc(RagDocument.published_at), desc(RagDocument.id))
            .limit(limit)
        )

    def _build_chunk(self, document: RagDocument, chunk_index: int, chunk_data: dict[str, int | str]) -> RagChunk:
        chunk_text = str(chunk_data["text"])
        # 向量化输入（embedding_text）= 标题 + 正文 ，让 embedding 模型感知主题
        embedding_text = self._build_embedding_text(document.title, chunk_text)
        return RagChunk(
            document_id=document.id,
            chunk_index=chunk_index,
            chunk_text=chunk_text,
            embedding_text=embedding_text,
            chunking_version=self.chunking_version,
            chunk_hash=self._hash_text(chunk_text),
            token_count=self._estimate_token_count(chunk_text),
            start_offset=int(chunk_data["start"]),
            end_offset=int(chunk_data["end"]),
            published_at=document.published_at,
            source_name=document.source_name,
            category=document.category,
            importance_score=document.importance_score or 0,
            sentiment=document.sentiment,
            extra_metadata={
                "document_title": document.title,
                "document_url": document.url,
                "source_type": document.source_type,
                "source_id": document.source_id,
            },
        )

    @staticmethod
    def _build_embedding_text(title: str | None, chunk_text: str) -> str:
        """构造 chunk 级向量化文本：标题\n正文段。

        title 为空或已在 chunk_text 中时，只用 chunk_text。
        """
        title = (title or "").strip()
        if title and title not in chunk_text:
            return f"{title}\n{chunk_text}"
        return chunk_text

    @staticmethod
    def _estimate_token_count(text: str) -> int:
        """中文字符 = 1 token ， 英文/数字单词 = 1 token ，直接相加"""
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        non_chinese_words = len(re.findall(r"[A-Za-z0-9_]+", text))
        return chinese_chars + non_chinese_words

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
