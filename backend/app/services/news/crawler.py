"""三源财经快讯抓取与入库。"""

import json
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sse import sse_manager
from app.models.news import (
    NewsItem,
    NewsItemEntity,
    NewsItemRelation,
    NewsItemTopic,
    NewsRawItem,
    NewsSource,
)

from .cls_parser import parse_cls_item
from .dto import ParsedEntity, ParsedNewsItem, ParsedRelation, ParsedTopic
from .sina_parser import parse_sina_item
from .wscn_parser import parse_wscn_item

logger = logging.getLogger(__name__)

PARSERS = {
    "cls": parse_cls_item,
    "wscn": parse_wscn_item,
    "sina": parse_sina_item,
}


class NewsCrawler:
    """三个快讯来源的抓取与入库逻辑。"""

    SOURCES: dict[str, dict[str, str]] = {
        "cls": {
            "name": "财联社",
            "url": "https://www.cls.cn/api/cache?app=CailianpressWeb&name=telegraph&os=web&sv=8.7.9",
        },
        "wscn": {
            "name": "华尔街见闻",
            "url": "https://api-one-wscn.awtmt.com/apiv1/content/lives",
        },
        "sina": {
            "name": "新浪财经",
            "url": "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=20&zhibo_id=152",
        },
    }

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # 采集与入库
    # ------------------------------------------------------------------

    async def fetch_all_sources(self) -> dict[str, int]:
        results: dict[str, int] = {}
        for source_code in self.SOURCES:
            results[source_code] = await self.fetch_remote_news(source_code)
        return results

    async def fetch_remote_news(self, source: str, source_type: str = "flash") -> int:
        """抓取一个来源。V1 仅支持 flash，参数保留用于调度器兼容。"""
        if source_type not in {"flash"}:
            logger.debug("Skip unsupported news content type: source=%s type=%s", source, source_type)
            return 0
        if source not in self.SOURCES:
            logger.warning("Unknown news source: %s", source)
            return 0

        try:
            # 1，抓取对应源数据
            items = await self._fetch_source_items(source)
            # 2. 保存数据
            return await self._save_news_batch(items, source)
        except Exception:
            logger.exception("News source crawl failed: source=%s", source)
            await self.db.rollback()
            return 0

    async def _fetch_source_items(self, source: str) -> list[dict[str, Any]]:
        """根据传入的源抓取对应快讯"""
        # 1. 根据不同源准备对应请求头 referer 请求参数......
        config = self.SOURCES[source]
        url = config["url"].strip()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        params: dict[str, Any] | None = None
        if source == "cls":
            headers["Referer"] = "https://www.cls.cn/"
        elif source == "wscn":
            params = {"channel": "global-channel", "client": "pc", "limit": 20}

        # 2. 调用httpx抓取数据
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()

        # 3. 根据源选择对应解析方式
        if source == "cls":
            items = payload.get("data", {}).get("roll_data", [])
        elif source == "wscn":
            if payload.get("code") != 20000:
                raise ValueError(f"华尔街见闻接口返回失败: {payload.get('message')}")
            items = payload.get("data", {}).get("items", [])
        else:
            result = payload.get("result", {})
            status = result.get("status", {})
            if status.get("code") != 0:
                raise ValueError(f"新浪财经接口返回失败: {status.get('msg')}")
            items = result.get("data", {}).get("feed", {}).get("list", [])

        if not isinstance(items, list):
            raise ValueError(f"来源 {source} 的快讯列表不是数组")
        return [item for item in items if isinstance(item, dict)]

    async def _save_news_batch(self, items: list[dict[str, Any]], source_code: str) -> int:
        # 1. 如果当前源在数据库不存在则新建记录
        source = await self._get_or_create_source(source_code)
        # 2. 获取对应源的解析方法
        parser = PARSERS[source_code]
        inserted_count = 0
        skip_empty = 0
        skip_short = 0

        # 3. 遍历源的每一条raw数据解析成可以入库的数据
        for payload in items:
            try:
                parsed_data = parser(payload)
                # ---- R1 / R2 硬剔除（爬取层拦截，news_items / news_raw_items 双表不落库） 目前该规则作用于财联社----
                if source_code == "cls":
                    skip_reason = self._check_hard_exclusion(parsed_data.content)
                    if skip_reason == "R1_EMPTY":
                        skip_empty += 1
                        continue
                    if skip_reason == "R2_SHORT":
                        skip_short += 1
                        continue
                # ---- 硬剔除结束 ----
                inserted = await self._insert_parsed_item(source, payload, parsed_data)
                inserted_count += int(inserted)
            except Exception:
                logger.exception(
                    "News item parse/insert failed: source=%s source_item_id=%s",
                    source_code,
                    payload.get("id"),
                )
        # 4. 入库数量大于0 则提交事务并发送广播通知前端增量拉取最新数据
        if inserted_count:
            await self.db.commit()
            await sse_manager.broadcast(
                json.dumps(
                    {"event": "news_flash", "source": source_code, "count": inserted_count},
                    ensure_ascii=False,
                )
            )
            logger.info("News batch inserted: source=%s count=%s", source_code, inserted_count)
        else:
            # 结束查询开启的只读事务，避免调度器后续阶段持有无用事务。
            await self.db.rollback()
        if skip_empty or skip_short:
            logger.info(
                "News hard-excluded: source=%s R1_empty=%d R2_short=%d",
                source_code, skip_empty, skip_short,
            )
        return inserted_count

    @staticmethod
    def _check_hard_exclusion(content: str | None) -> str | None:
        """R1 / R2 硬剔除判定（爬取层第一道防线）。

        返回值：
          - None       : 通过，正常入库
          - "R1_EMPTY" : R1 空正文（VIP 付费引流等，parser 层可能漏拦，此处兜底）
          - "R2_SHORT" : R2 正文 <15 字（底线防护，实际拦截量趋近于零）
        """
        if content is None:
            return "R1_EMPTY"
        stripped = content.strip()
        if not stripped:
            return "R1_EMPTY"
        # 15 字 ≈ 2-3 个完整词/短语，低于此阈值的快讯大概率是截断碎片
        if len(stripped) < 15:
            return "R2_SHORT"
        return None

    async def _get_or_create_source(self, source_code: str) -> NewsSource:
        """如果当前配置抓取源在来源表中不存在则创建记录"""
        result = await self.db.execute(select(NewsSource).where(NewsSource.code == source_code))
        source = result.scalar_one_or_none()
        if source:
            return source

        source = NewsSource(code=source_code, name=self.SOURCES[source_code]["name"], enabled=True)
        self.db.add(source)
        await self.db.flush()
        return source

    async def _insert_parsed_item(self, source: NewsSource, payload: dict[str, Any], parsed: ParsedNewsItem) -> bool:
        """数据入库"""
        # 1. 开启嵌套事务（行级隔离）
        # 使用 PostgreSQL 的 SAVEPOINT 机制。如果某条快讯入库失败，只会回滚这一条，不影响同批次的其他快讯。
        async with self.db.begin_nested():
            # 2. 幂等写入原始 JSON 遇冲突时返回 None，新增时返回新 ID
            raw_insert = (
                pg_insert(NewsRawItem)
                .values(
                    source_id=source.id,
                    source_item_id=parsed.source_item_id,
                    payload=payload,
                    published_at=parsed.published_at,
                )
                .on_conflict_do_nothing(constraint="uq_news_raw_source_item")
                .returning(NewsRawItem.id)
            )
            raw_result = await self.db.execute(raw_insert)
            raw_item_id = raw_result.scalar_one_or_none()
            if raw_item_id is None:
                return False  # ← 该快讯已存在，直接跳过幂等写入原始 JSON 遇

            # 3. 写入结构化快讯主表
            news_item = NewsItem(
                raw_item_id=raw_item_id,
                source_id=source.id,
                content_type=parsed.content_type,
                title=parsed.title,
                content=parsed.content,
                is_source_important=parsed.is_source_important,
                published_at=parsed.published_at,
            )
            self.db.add(news_item)
            await self.db.flush()  # flush 而非 commit，使 ID 立即可用

            # 4. 批量写入关联表
            self.db.add_all(self._build_topic_models(news_item.id, parsed.topics))
            self.db.add_all(self._build_entity_models(news_item.id, parsed.entities))
            self.db.add_all(self._build_relation_models(news_item.id, parsed.relations))
            await self.db.flush()
            return True

    @staticmethod
    def _build_topic_models(news_item_id: int, topics: list[ParsedTopic]) -> list[NewsItemTopic]:
        """主题标签（来源频道/分类）"""
        models: list[NewsItemTopic] = []
        seen: set[str] = set()
        for topic in topics:
            if not topic.name or topic.name in seen:
                continue
            seen.add(topic.name)
            models.append(
                NewsItemTopic(
                    news_item_id=news_item_id,
                    name=topic.name,
                )
            )
        return models

    @staticmethod
    def _build_entity_models(news_item_id: int, entities: list[ParsedEntity]) -> list[NewsItemEntity]:
        """关联实体（股票/基金代码）"""
        models: list[NewsItemEntity] = []
        seen: set[tuple[str, str]] = set()
        for entity in entities:
            key = (entity.entity_type, entity.symbol)
            if not entity.symbol or key in seen:
                continue
            seen.add(key)
            models.append(
                NewsItemEntity(
                    news_item_id=news_item_id,
                    entity_type=entity.entity_type,
                    symbol=entity.symbol,
                    name=entity.name,
                )
            )
        return models

    @staticmethod
    def _build_relation_models(news_item_id: int, relations: list[ParsedRelation]) -> list[NewsItemRelation]:
        """外部原文链接"""
        models: list[NewsItemRelation] = []
        seen: set[str] = set()
        for relation in relations:
            if not relation.url or relation.url in seen:
                continue
            seen.add(relation.url)
            models.append(NewsItemRelation(news_item_id=news_item_id, url=relation.url))
        return models
