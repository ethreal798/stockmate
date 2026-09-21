"""基金领域相关的 Agent 工具定义。

关键要点：
1. StructuredTool.from_function + Pydantic args_schema → LangChain 官方推荐
2. 工具函数签名是同步的（LangGraph ToolNode 会用 asyncio.to_thread 执行，
   但我们内部自己 await 异步 db 调用，所以用 async def）
3. 工具返回 str 即可，ToolNode 会自动包装成 ToolMessage
4. 工厂函数 create_fund_tools(context) 用闭包把 db 注入进去
"""

import json

from langchain_core.tools import StructuredTool

from app.core.database import async_session_factory
from app.services.agent.tools.base import ToolContext
from app.services.agent.tools.schemas import SearchFundsInput, GetFundDetailInput
from app.services.fund.query.catalog import FundCatalogQueryService


async def _do_search_funds(keyword: str, limit: int, ctx: ToolContext) -> str:
    """实际执行搜索，格式化结果为文本返回给LLM"""
    async with async_session_factory() as db:
        service = FundCatalogQueryService(db)
        rows = await service.search_funds(keyword=keyword, limit=limit, user_id=ctx.user_id)

    if not rows:
        return f"没有找到与关键词【{keyword}】匹配基金。请尝试其他关键词。"

    lines = [f"共找到 {len(rows)} 只匹配基金：", ""]
    for i, row in enumerate(rows, 1):
        code = row["code"]
        name = row["name"]
        category = "货币" if row["is_hb"] else ("场内" if row["is_exchange"] else "开放式")
        latest = row.get("latest") or {}
        # 选几个关键指标展示， 避免太长被截断
        quick_stats = []

        for k in ("return_1m_pct", "return_3m_pct", "return_1y_pct", "annualized_7d_pct", "income_per_10k"):
            v = latest.get(k)
            if v is not None:
                quick_stats.append(f"{k}: {v}")

        lines.append(
            f"{i}. [{category}] {code} {name}"
            + (f" | {' '.join(quick_stats)}" if quick_stats else "")
            + (" | 已自选" if row["is_in_watchlist"] else "")
        )

    return "\n".join(lines)


async def _do_get_fund_detail(code: str, ctx: ToolContext) -> str:
    """查询单只基金的完整详情。"""
    async with async_session_factory() as db:
        service = FundCatalogQueryService(db)
        detail = await service.get_fund_detail(code)

    if detail is None:
        return f"未找到基金代码【{code}】对应的基金。请确认代码是否正确。"

    # 用 JSON 格式返回给 LLM，结构化数据它更容易解析
    # 但要注意截断过长的字段
    latest = detail.get("latest")
    summary = {
        "code": detail["code"],
        "name": detail["name"],
        "type": detail["fund_type"],
        "category": "货币" if detail["is_hb"] else ("场内" if detail["is_exchange"] else "开放式"),
        "latest": latest,
    }
    return f"基金 {code} 详情：\n```json\n{json.dumps(summary, ensure_ascii=False, indent=2, default=str)}\n```"


def create_fund_tools(context: ToolContext) -> list[StructuredTool]:
    """创建基金工具实例，把 context 绑到闭包里。
        注：LangGraph ToolNode 会同步执行 tool.invoke()。
        但我们的工具内部要调 async db，所以用 asyncio.run_coroutine_threadsafe
        或者（更简单）让 ToolNode 在创建时指定 coroutine_mode。
    """
    async def _search_funds_async(keyword: str, limit: int = 5) -> str:
        return await _do_search_funds(keyword, limit, context)

    async def _get_fund_detail_async(code: str) -> str:
        return await _do_get_fund_detail(code, context)

    return [
        StructuredTool.from_function(
            coroutine=_search_funds_async,
            name="search_funds",
            description=(
                "搜索基金列表。当用户提到「找基金」「搜一下 XX 基金」「看看有没有 XX」"
                "或者需要根据关键词查找基金代码时使用此工具。"
                "不要在用户已明确给出基金代码时调用搜索，应直接用 get_fund_detail 查询详情。"
            ),
            args_schema=SearchFundsInput
        ),
        StructuredTool.from_function(
            coroutine=_get_fund_detail_async,
            name="get_fund_detail",
            description=(
                "查询单只基金的详细信息（净值、收益率、类型等）。"
                "当用户给出明确的 6 位基金代码（如 110022）或在搜索结果中想进一步了解某只基金时使用。"
                "需要先通过 search_funds 搜索拿到基金代码，再用此工具查详情。"
            ),
            args_schema=GetFundDetailInput,
        )
    ]
