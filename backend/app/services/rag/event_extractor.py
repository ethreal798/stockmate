"""RAG Stage 3：LLM 事件抽取服务。

处理流程（单文档视角）：
  ① R4 分流（程序正则）→ 命中「新闻精选|要闻|大事提醒」→ 跳过
  ② 读 extra_metadata 锚点（topics=subjects，entities=stock_list）
  ③ 组装 LLM 输入（锚点 + title + content + taxonomy）
  ④ LLM 输出（约束 ≤3 事件）→ 容错 JSON 解析
  ⑤ 组装 rag_events（有 stocks 则 entity_code 直接用，否则 LLM 推断）
  ⑥ 批量写入 + 更新 processing_stage

与 RagPipelineService 的衔接：由 Pipeline 在 Step4 调用 extract_pending()，
Stage3 失败降级不影响 pipeline 整体 success（仅 warning 日志）。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.rag import RagDocument, RagEvent
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


# R4 分流正则：聚合摘要类不做事件抽取（避免重复计数）
_R4_SUMMARY_PATTERN = re.compile(r"新闻精选|要闻|大事提醒")


class EventExtractorService:
    """LLM 金融资讯事件抽取服务。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.llm_service = LLMService()
        self._taxonomy = self._load_taxonomy()

    # ──────────────────────────────────────────────────────────
    # 主入口
    # ──────────────────────────────────────────────────────────

    async def extract_pending(
        self,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """抽取 processing_stage='embedded' 的待处理文档的事件。

        失败隔离：单文档失败标 event_failed，不阻断其他文档。
        R4 命中 → 标 events_done，不写 rag_events（正常分支）。

        返回：
            stats 字典，含 scanned/extracted/skipped_r4/failed/saved_events_count
        """
        effective_limit = limit or settings.RAG_EVENT_EXTRACTION_LIMIT_PER_DRAIN
        # 1. 获取未进行事件抽取的文档
        documents = await self._get_pending_documents(effective_limit)
        stats: dict[str, Any] = {
            "scanned": len(documents),
            "extracted": 0,
            "skipped_r4": 0,
            "failed": 0,
            "saved_events_count": 0,
            "model": settings.RAG_EVENT_EXTRACTION_LLM_MODEL,
        }

        if not documents:
            return stats

        # 顺序处理（AsyncSession 非线程安全，不能并发共享同一个 session）
        # Semaphore 挪到 _call_llm_extract 内部，限制 LLM 调用并发度
        for doc in documents:
            result = await self._extract_document_safe(doc)
            if result.get("skipped_r4"):
                stats["skipped_r4"] += 1
            elif result.get("success"):
                stats["extracted"] += 1
                stats["saved_events_count"] += result.get("events_saved", 0)
            elif result.get("failed"):
                stats["failed"] += 1

        return stats

    # ──────────────────────────────────────────────────────────
    # 内部：获取待处理文档
    # ──────────────────────────────────────────────────────────

    async def _get_pending_documents(self, limit: int) -> list[RagDocument]:
        """取 processing_stage='embedded'（或 'event_failed' 可重试）的文档。"""
        stmt = (
            select(RagDocument)
            .where(RagDocument.processing_stage.in_(["embedded", "event_failed"]))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ──────────────────────────────────────────────────────────
    # 内部：单文档处理（带信号量 + 异常隔离）
    # ──────────────────────────────────────────────────────────

    async def _extract_document_safe(self, doc: RagDocument) -> dict[str, Any]:
        """异常隔离的单文档处理。

        AsyncSession 非并发安全，这里顺序处理，异常时先 rollback 再 mark_failed，
        避免 session 留在 broken/pending rollback 状态。
        """
        try:
            return await self._extract_document(doc)
        except Exception as exc:
            logger.error("Event extraction failed for doc %d: %s", doc.id, exc, exc_info=True)
            # 关键：先 rollback，再 mark_failed（mark_failed 内部也要 commit）
            try:
                await self.db.rollback()
            except Exception:
                logger.warning("Rollback failed for doc %d", doc.id)
            try:
                await self._mark_failed(doc.id, str(exc))
            except Exception as mark_exc:
                logger.error("Failed to mark_failed for doc %d: %s", doc.id, mark_exc)
            return {"failed": True, "doc_id": doc.id, "error": str(exc)}

    async def _extract_document(self, doc: RagDocument) -> dict[str, Any]:
        """单文档完整处理流程：R4 分流 → LLM 抽取 → rag_events 写入。"""

        # ① R4 分流检查
        if self._check_r4_skip(doc.title):
            await self._mark_done(doc.id)
            return {"skipped_r4": True, "doc_id": doc.id}

        # ② 读结构化锚点
        anchors = self._extract_anchors(doc)
        topics = anchors["topics"]
        stocks = anchors["stocks"]

        # ③ LLM 调用
        llm_events = await self._call_llm_extract(
            title=doc.title,
            content=doc.content,
            topics=topics,
            stocks=stocks,
        )

        if not llm_events:
            # LLM 返回空事件（可能是中性新闻无显著事件），也算正常完成
            await self._mark_done(doc.id)
            return {"success": True, "doc_id": doc.id, "events_saved": 0}

        # ④ 组装 rag_events 并写入
        saved_count = await self._save_events(doc, llm_events, stocks)

        # ⑤ 标记完成
        await self._mark_done(doc.id)
        return {"success": True, "doc_id": doc.id, "events_saved": saved_count}

    # ──────────────────────────────────────────────────────────
    # 内部：R4 分流 + 锚点提取
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _check_r4_skip(title: str | None) -> bool:
        """聚合摘要类新闻跳过事件抽取（避免重复计数）。"""
        # todo 是否以标题作为参考基准 待确认
        if not title:
            return False
        return bool(_R4_SUMMARY_PATTERN.search(title))

    @staticmethod
    def _extract_anchors(doc: RagDocument) -> dict[str, Any]:
        """从 extra_metadata 提取结构化锚点。"""
        meta = doc.extra_metadata or {}
        raw_topics = meta.get("topics") or []
        raw_entities = meta.get("entities") or []

        # subjects 锚点（纯字符串列表）
        topics: list[str] = [
            str(t).strip() for t in raw_topics
            if t is not None and str(t).strip()
        ]

        # stock_list 锚点（只留 type=stock 且有 symbol 的）
        stocks: list[dict[str, str]] = []
        for e in raw_entities:
            if not isinstance(e, dict):
                continue
            if e.get("type") == "stock" and e.get("symbol"):
                stocks.append({"name": str(e.get("name", "")).strip(), "symbol": str(e["symbol"]).strip()})

        return {"topics": topics, "stocks": stocks}

    # ──────────────────────────────────────────────────────────
    # 内部：LLM 调用 + Prompt + JSON 容错
    # ──────────────────────────────────────────────────────────

    async def _call_llm_extract(
        self,
        *,
        title: str | None,
        content: str,
        topics: list[str],
        stocks: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        """调用 LLM 做事件抽取，返回解析后的事件列表。"""
        messages = self._build_prompt_messages(title, content, topics, stocks)

        llm_result = await self.llm_service.generate(
            messages=messages,
            model=settings.RAG_EVENT_EXTRACTION_LLM_MODEL,
            temperature=0.1,
            response_format={"type": "json_object"},
            extra_params={"enable_thinking": False},
        )

        raw_content = llm_result.get("content", "")
        parsed = self._parse_llm_json(raw_content)
        events = self._normalize_events(parsed)
        return events

    def _build_prompt_messages(
        self,
        title: str | None,
        content: str,
        topics: list[str],
        stocks: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """组装 system + user prompt。"""
        today = date.today().isoformat()
        taxonomy_json = json.dumps(self._taxonomy.get("categories", {}), ensure_ascii=False, indent=2)
        max_events = settings.RAG_EVENT_EXTRACTION_MAX_EVENTS

        system_prompt = (
            f"你是金融资讯事件抽取专家。你的任务是从单条新闻中抽取关键事件，"
            f"为每个事件标注行业分类、实体、情绪和置信度。\n\n"
            f"【行业分类体系】（必须从中选择一级和二级，一级用于聚合统计）：\n"
            f"{taxonomy_json}\n\n"
            f"【情绪标签枚举】positive（利好）、negative（利空）、mixed（多空交织）、neutral（中性）\n"
            f"【约束】\n"
            f"- 最多抽取 {max_events} 个事件\n"
            f"- confidence 范围 0.0-1.0，表示你对该事件判断的确信程度\n"
            f"- entity_type 可选值：stock / industry / macro / person / org / concept\n"
            f"- 如果新闻无显著事件（如天气、球赛、无关金融），返回 events 为空数组\n"
            f"- 同方向事件合并，不要碎片化重复抽取"
        )

        # 组装锚点提示（有则注入，无则省略）
        anchors_text = ""
        if topics:
            anchors_text += f"\n【已知行业锚点（来源财联社 subjects，仅供参考映射到 taxonomy）】\n{', '.join(topics)}\n"
        if stocks:
            stock_lines = [f"  - {s['symbol']}: {s['name']}" for s in stocks]
            anchors_text += f"\n【已知股票锚点（来源财联社 stock_list，可直接作为 entity_code/entity_name）】\n" + "\n".join(stock_lines) + "\n"

        user_prompt = (
            f"今日日期：{today}\n\n"
            f"【新闻标题】\n{title or '（无标题）'}\n\n"
            f"【新闻正文】\n{content}\n"
            f"{anchors_text}\n"
            f"请输出 JSON 格式（不要输出 Markdown 代码块标记），结构如下：\n"
            f'{{\n'
            f'  "events": [\n'
            f'    {{\n'
            f'      "entity_type": "stock|industry|macro|...",\n'
            f'      "entity_name": "实体名称（如有锚点 stock_list，优先使用锚点名称）",\n'
            f'      "entity_code": "股票代码（如有锚点 stock_list，优先使用锚点 symbol；行业/宏观事件可留空）",\n'
            f'      "industry_category": "一级行业（必须从分类体系中选择）",\n'
            f'      "industry_tag": "二级行业（必须从分类体系中选择）",\n'
            f'      "event_action": "事件核心描述，≤50字",\n'
            f'      "sentiment": "positive|negative|mixed|neutral",\n'
            f'      "confidence": 0.0-1.0\n'
            f'    }}\n'
            f'  ]\n'
            f'}}\n'
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    @staticmethod
    def _parse_llm_json(raw: str) -> dict[str, Any]:
        """容错解析 LLM 返回的 JSON。

        qwen3.8-flash 即使 response_format=json_object 偶尔也会
        在 JSON 前后附加文字或代码块标记，这里做兜底修复。
        """
        if not raw:
            return {}

        text = raw.strip()

        # 去掉 ```json ... ``` 代码块标记
        if text.startswith("```"):
            lines = text.split("\n")
            # 去掉首行 ```json 或 ```
            lines = lines[1:]
            # 去掉末行 ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # 优先直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 兜底：截取首个 { 到末个 }
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            trimmed = text[first_brace : last_brace + 1]
            try:
                return json.loads(trimmed)
            except json.JSONDecodeError:
                logger.warning("Failed to parse LLM JSON even after trim: %s", text[:200])

        return {}

    @staticmethod
    def _normalize_events(parsed: dict[str, Any]) -> list[dict[str, Any]]:
        """从解析结果里提取 events 数组，做字段清洗。"""
        if not isinstance(parsed, dict):
            return []

        raw_events = parsed.get("events")
        if not isinstance(raw_events, list):
            return []

        max_events = settings.RAG_EVENT_EXTRACTION_MAX_EVENTS
        normalized: list[dict[str, Any]] = []

        for evt in raw_events[:max_events]:
            if not isinstance(evt, dict):
                continue

            # confidence 清洗
            conf_raw = evt.get("confidence")
            try:
                confidence = float(conf_raw) if conf_raw is not None else None
                if confidence is not None:
                    confidence = max(0.0, min(1.0, confidence))  # clamp
            except (ValueError, TypeError):
                confidence = None

            # sentiment 清洗
            sentiment = str(evt.get("sentiment", "")).strip().lower() or None
            if sentiment not in {"positive", "negative", "mixed", "neutral"}:
                sentiment = None

            # 组装清洗后的事件
            normalized.append({
                "entity_type": str(evt.get("entity_type", "")).strip() or "industry",
                "entity_name": str(evt.get("entity_name", "")).strip() or None,
                "entity_code": str(evt.get("entity_code", "")).strip() or None,
                "industry_category": str(evt.get("industry_category", "")).strip() or None,
                "industry_tag": str(evt.get("industry_tag", "")).strip() or None,
                "event_action": str(evt.get("event_action", "")).strip() or None,
                "sentiment": sentiment,
                "confidence": confidence,
            })

        return normalized

    # ──────────────────────────────────────────────────────────
    # 内部：组装 + 写入 rag_events
    # ──────────────────────────────────────────────────────────

    async def _save_events(
        self,
        doc: RagDocument,
        llm_events: list[dict[str, Any]],
        stocks: list[dict[str, str]],
    ) -> int:
        """组装 rag_events 并批量写入。

        规则：
          - 有 stocks 锚点 → 为每只股票各生成 1 行 rag_events（entity_code 用锚点）
          - 无 stocks 锚点 → LLM 每个事件生成 1 行（entity_code 可能为空）
        """
        batch: list[RagEvent] = []

        if stocks:
            # 情况 A：有 stock_list 锚点
            # 每个 LLM 事件 × 每只股票 = 多行（共享 industry_category/event_action）
            for llm_evt in llm_events:
                for stock in stocks:
                    batch.append(RagEvent(
                        document_id=doc.id,
                        entity_type="stock",
                        entity_name=stock["name"],
                        entity_code=stock["symbol"],
                        industry_category=llm_evt.get("industry_category"),
                        industry_tag=llm_evt.get("industry_tag"),
                        event_action=llm_evt.get("event_action"),
                        sentiment=llm_evt.get("sentiment"),
                        confidence=llm_evt.get("confidence"),
                        event_time=doc.published_at,
                    ))
        else:
            # 情况 B：无 stock_list 锚点，直接用 LLM 推断结果
            for llm_evt in llm_events:
                batch.append(RagEvent(
                    document_id=doc.id,
                    entity_type=llm_evt.get("entity_type", "industry"),
                    entity_name=llm_evt.get("entity_name"),
                    entity_code=llm_evt.get("entity_code"),
                    industry_category=llm_evt.get("industry_category"),
                    industry_tag=llm_evt.get("industry_tag"),
                    event_action=llm_evt.get("event_action"),
                    sentiment=llm_evt.get("sentiment"),
                    confidence=llm_evt.get("confidence"),
                    event_time=doc.published_at,
                ))

        if not batch:
            return 0

        # 批量写入
        for event in batch:
            self.db.add(event)
        await self.db.commit()
        return len(batch)

    # ──────────────────────────────────────────────────────────
    # 内部：状态更新
    # ──────────────────────────────────────────────────────────

    async def _mark_done(self, doc_id: int) -> None:
        """标记文档事件抽取完成。"""
        stmt = (
            RagDocument.__table__.update()
            .where(RagDocument.__table__.c.id == doc_id)
            .values(processing_stage="events_done", processing_error=None)
        )
        await self.db.execute(stmt)
        await self.db.commit()

    async def _mark_failed(self, doc_id: int, error: str) -> None:
        """标记文档事件抽取失败（可被后续 retry）。"""
        try:
            stmt = (
                RagDocument.__table__.update()
                .where(RagDocument.__table__.c.id == doc_id)
                .values(processing_stage="event_failed", processing_error=error[:2000])
            )
            await self.db.execute(stmt)
            await self.db.commit()
        except Exception:
            await self.db.rollback()

    # ──────────────────────────────────────────────────────────
    # 内部：taxonomy 加载
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _load_taxonomy() -> dict[str, Any]:
        """加载 industry_taxonomy.json。"""
        # 和 industry_taxonomy.json 同在 app/config 目录下
        config_dir = Path(__file__).resolve().parent.parent.parent / "config"
        taxonomy_path = config_dir / "industry_taxonomy.json"

        try:
            with open(taxonomy_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Failed to load industry_taxonomy.json: %s", exc)
            return {"version": "unknown", "categories": {}}
