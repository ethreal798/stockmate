"""RAG 检索工具定义。

关键要点（和 fund_tools.py 保持一致）：
1. 内部 async with async_session_factory() 租 session，用完即还（lazy acquire）
2. 复用项目已有的 RetrievalService（混合召回 BM25+向量+RRF）
3. 复用 RagService._build_context / _build_citations 静态方法格式化
4. citations 用 HTML 注释标记藏在返回正文末尾，executor 侧正则提取
5. 工具返回 str，ToolNode 自动包成 ToolMessage
"""

import json
import logging
import re

from langchain_core.tools import StructuredTool

from app.core.database import async_session_factory
from app.services.agent.tools.base import ToolContext
from app.services.agent.tools.schemas import SearchNewsInput
from app.services.rag.rag_service import RagService
from app.services.rag.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)

# Citation 标记格式（统一用无空格版本，方便正则匹配）
_CITATION_MARKER_OPEN = "<!--CITATIONS:"
_CITATION_MARKER_CLOSE = "-->"


def _extract_citations_from_tool_content(content: str) -> list[dict] | None:
    """从 ToolMessage.content 里的 <!--CITATIONS:...--> 标记解析 citations。

    Returns:
        None  — 没有标记（不是每个工具都会带 citations，正常情况）
        []   — 有标记但 JSON 解析失败（警告级别）
        list — 成功
    """
    match = re.search(
        rf"{re.escape(_CITATION_MARKER_OPEN)}(.*?){re.escape(_CITATION_MARKER_CLOSE)}",
        content,
        re.DOTALL,
    )
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse CITATIONS marker in tool output")
        return []


def _strip_citations_marker(content: str) -> str:
    """把 <!--CITATIONS:...--> 标记从 ToolMessage.content 移除。"""
    return re.sub(
        rf"^\s*{re.escape(_CITATION_MARKER_OPEN)}.*?{re.escape(_CITATION_MARKER_CLOSE)}\s*$",
        "",
        content,
        flags=re.DOTALL | re.MULTILINE,
    ).rstrip()


def _build_citation_marker(citations: list[dict]) -> str:
    """拼接 <!--CITATIONS:...--> 标记。"""
    payload = json.dumps(citations, ensure_ascii=False, default=str)
    return f"\n\n{_CITATION_MARKER_OPEN}{payload}{_CITATION_MARKER_CLOSE}"


async def _do_search_news(query: str, top_k: int, days: int, ctx: ToolContext) -> str:
    """实际执行检索 → 格式化 → 拼接 citations 标记。"""
    # 自己租 session，用完即还（和 fund_tools 一致）
    async with async_session_factory() as db:
        retrieval = await RetrievalService(db).retrieve(query=query, top_k=top_k, days=days)

    items = retrieval["items"]
    if not items:
        return f"未检索到最近 {days} 天与【{query}】相关的资讯。可以试试扩大时间范围或换关键词。"

    # 复用项目已有的格式化方法（不要自己写！）
    formatted = RagService._build_context(items)
    citations = RagService._build_citations(items)
    marker = _build_citation_marker(citations)

    return f"检索到 {len(items)} 条资讯：\n\n{formatted}{marker}"


def create_rag_tools(context: ToolContext) -> list[StructuredTool]:
    """创建 RAG 工具实例，把 context 绑到闭包里。"""

    async def _search_news_async(query: str, top_k: int = 5, days: int = 7) -> str:
        return await _do_search_news(query, top_k, days, context)

    return [
        StructuredTool.from_function(
            coroutine=_search_news_async,
            name="search_news",
            description=(
                "检索新闻资讯库。当用户询问市场动态、政策变化、板块行情、新闻事件、"
                "某个行业或公司的最新消息时使用此工具。"
                "不要用来查基金净值或基金代码（那是 search_funds / get_fund_detail 的事）。"
            ),
            args_schema=SearchNewsInput,
        )
    ]
