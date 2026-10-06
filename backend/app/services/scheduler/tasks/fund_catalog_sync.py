"""基金目录（分类）定时同步任务。"""

from __future__ import annotations

import logging
from typing import Any

from app.services.fund.sync.catalog import FundCatalogSyncService
from app.services.scheduler.task_registry import register_task

logger = logging.getLogger(__name__)


@register_task(
    task_id="fund_catalog_sync",
    trigger_config={"cron": "0 0 * * 1"},
)
async def fund_catalog_sync(db, params: dict[str, Any]) -> None:
    """基金目录（分类）定时同步。

    每周一 00:00（周日 24:00）执行一次，
    同步全量基金代码、名称、类型及 is_hb / is_exchange 标记。
    """
    service = FundCatalogSyncService(db)
    result = await service.fetch_and_sync()
    logger.info(f"基金目录定时同步完成: {result}")
