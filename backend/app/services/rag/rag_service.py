"""RAG 问答服务。"""

import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.rag import RagQueryLog
from app.services.llm_service import LLMService
from app.services.rag.retrieval_service import RetrievalService


class RagService:
    """检索增强问答编排服务。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.retrieval_service = RetrievalService(db)
        self.llm_service = LLMService()

    async def answer(
        self,
        message: str,
        conversation_id: str | None = None,
        top_k: int = 8,
        days: int | None = 7,
        model: str | None = None,
    ) -> dict[str, Any]:
        """执行 RAG 问答。"""
        # 1. 准备初始必须变量
        start_time = time.perf_counter()
        conversation_id = conversation_id or str(uuid.uuid4())
        model_name = model  # or settings.AI_MODEL_NAME

        # 2. 执行检索流程
        retrieval = await self.retrieval_service.retrieve(
            query=message,
            top_k=top_k,
            days=days,
        )
        retrieved_items = retrieval["items"]
        # 3. 提取检索结果引用 去掉正文
        citations = self._build_citations(retrieved_items)

        if not retrieved_items:
            answer = "暂未检索到可用于回答的新闻资料。你可以扩大时间范围，或先执行新闻入库、切块和向量化任务。"
            usage = None
        else:
            # 4. 组装提示词 调用大模型生成回复
            messages = self._build_messages(message, retrieved_items)
            llm_result = await self.llm_service.generate(messages=messages, model=model_name, temperature=0.2)
            answer = llm_result["content"]
            usage = llm_result.get("usage")
            model_name = llm_result.get("model") or model_name

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        await self._save_query_log(
            conversation_id=conversation_id,
            user_query=message,
            model_name=model_name,
            answer=answer,
            citations=citations,
            retrieved_chunk_ids=[item["chunk_id"] for item in retrieved_items],
            days=days,
            top_k=top_k,
            latency_ms=latency_ms,
        )

        return {
            "conversation_id": conversation_id,
            "answer": answer,
            "citations": citations,
            "retrieved_count": len(retrieved_items),
            "model": model_name,
            "usage": usage,
        }

    def _build_messages(self, question: str, items: list[dict[str, Any]]) -> list[dict[str, str]]:
        """ 组装检索结果与提示词 提问大模型 """
        context = self._build_context(items)
        system_prompt = (
            "你是一个中文金融资讯 RAG 助手。请只基于用户提供的检索资料回答，不要编造未出现的事实。"
            "回答需要清晰、克制，并区分事实、推断和不确定性。"
            "这不是投资建议，不要给出确定性的买卖指令。"
            "如资料不足，请直接说明资料不足。"
        )
        user_prompt = (
            f"用户问题：{question}\n\n"
            f"检索资料：\n{context}\n\n"
            "请按以下结构回答：\n"
            "1. 结论\n"
            "2. 关键依据\n"
            "3. 可能影响\n"
            "4. 风险与不确定性\n"
            "引用资料时请使用 [1]、[2] 这样的编号。"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    @staticmethod
    def _build_context(items: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for index, item in enumerate(items, start=1):
            published_at = item["published_at"].isoformat(sep=" ") if item.get("published_at") else "未知时间"
            title = item.get("title") or "无标题"
            source_name = item.get("source_name") or "未知来源"
            lines.append(
                f"[{index}] 来源：{source_name}；时间：{published_at}；标题：{title}；"
                f"分类：{item.get('category') or '未知'}；内容：{item['content']}"
            )
        return "\n".join(lines)

    @staticmethod
    def _build_citations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """ 从完整检索结果里剥掉 chunk 正文，只留来源/链接/分数等元信息 ——给前端展示引用来源 + 给后端审计留快照。 """
        citations: list[dict[str, Any]] = []
        for index, item in enumerate(items, start=1):
            published_at = item.get("published_at")
            citations.append(
                {
                    "index": index,
                    "chunk_id": item["chunk_id"],
                    "document_id": item["document_id"],
                    "title": item.get("title"),
                    "source_name": item.get("source_name"),
                    "url": item.get("url"),
                    "published_at": published_at.isoformat() if published_at else None,
                    "score": item.get("score"),
                    "match_type": item.get("match_type"),
                }
            )
        return citations

    async def _save_query_log(
        self,
        conversation_id: str,
        user_query: str,
        model_name: str,
        answer: str,
        citations: list[dict[str, Any]],
        retrieved_chunk_ids: list[int],
        days: int | None,
        top_k: int,
        latency_ms: int,
    ) -> None:
        self.db.add(
            RagQueryLog(
                conversation_id=conversation_id,
                user_query=user_query,
                query_intent="news_qa",
                query_filters={"days": days, "top_k": top_k},
                retrieved_chunk_ids=retrieved_chunk_ids,
                model_name=model_name,
                answer=answer,
                citations=citations,
                latency_ms=latency_ms,
            )
        )
        await self.db.commit()
