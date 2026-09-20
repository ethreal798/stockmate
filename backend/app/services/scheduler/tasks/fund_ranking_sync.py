"""基金排行定时同步任务。"""

from __future__ import annotations

import logging
from typing import Any

from app.services.fund.sync.ranking import FundRankingSyncService
from app.services.scheduler.task_registry import register_task

logger = logging.getLogger(__name__)


@register_task(
    task_id="fund_ranking_sync",
    trigger_config={"cron": "0 20,21,22,23 * * 1-5"},
)
async def fund_ranking_sync(db, params: dict[str, Any]) -> None:
    """基金排行定时同步。

    交易日（周一至周五）20:00、21:00、22:00、23:00 各执行一次，
    覆盖开放式基金净值陆续更新的时段。
    """
    service = FundRankingSyncService(db)
    await service.fetch_and_sync()
    logger.info("基金排行定时同步完成")
