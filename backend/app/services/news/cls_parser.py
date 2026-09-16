"""财联社快讯解析器。"""

import re
from typing import Any

# 财联社 content 格式为 【标题】正文，需要剥离标题前缀（title 字段已单独提供）
TITLE_PREFIX_RE = re.compile(r"^【([^】]+)】\s*(.*)$", re.S)

from .dto import ParsedEntity, ParsedNewsItem, ParsedRelation, ParsedTopic
from .normalization import (
    clean_text,
    epoch_seconds,
    normalize_stock_symbol,
    optional_str,
)


def parse_cls_item(item: dict[str, Any]) -> ParsedNewsItem:
    source_item_id = optional_str(item.get("id"))
    if not source_item_id:
        raise ValueError("财联社快讯缺少 id")

    raw_content = clean_text(item.get("content") or item.get("brief"))

    title = optional_str(item.get("title"))
    content = raw_content
    # 如果 content 包含【标题】前缀，剥离掉；若 title 缺失则用提取的标题兜底
    title_match = TITLE_PREFIX_RE.match(raw_content)
    if title_match:
        extracted_title = title_match.group(1).strip() or None
        content = title_match.group(2).strip() or raw_content
        if not title and extracted_title:
            title = extracted_title

    level = (optional_str(item.get("level")) or "").upper() or None

    # 外部原文只作为关联记录保存，不进入快讯主表。
    original_url = optional_str(item.get("assocArticleUrl"))

    topics: list[ParsedTopic] = []
    for subject in item.get("subjects") or []:
        if not isinstance(subject, dict):
            continue
        name = optional_str(subject.get("subject_name"))
        if not name:
            continue
        topics.append(ParsedTopic(name=name))

    entities: list[ParsedEntity] = []
    for stock in item.get("stock_list") or []:
        if not isinstance(stock, dict):
            continue
        name = optional_str(stock.get("name"))
        symbol = normalize_stock_symbol(stock.get("StockID"))
        if not symbol:
            continue
        entities.append(
            ParsedEntity(
                entity_type="stock",
                name=name or symbol,
                symbol=symbol,
            )
        )

    relations: list[ParsedRelation] = []
    if original_url:
        relations.append(ParsedRelation(url=original_url))

    return ParsedNewsItem(
        source_item_id=source_item_id,
        published_at=epoch_seconds(item.get("ctime")),
        content=content,
        title=title,
        is_source_important=level in {"A", "B"},
        topics=topics,
        entities=entities,
        relations=relations,
    )
