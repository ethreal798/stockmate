"""东方财富三个基金排行接口的标准化与最新快照入库。"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fund import Fund, FundExchangeRankLatest, FundMoneyRankLatest, FundOpenRankLatest
from app.services.fund.common.utils import (
    iter_batches,
    normalize_date,
)
from app.services.fund.sources.ranking import fetch_rank_frames

logger = logging.getLogger(__name__)


class FundRankingSyncService:
    """三个排行全部校验通过后，在同一数据库事务内更新快照。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def fetch_and_sync(self) -> dict[str, int]:
        """同步入口"""
        # 1.抓取东财基金排行数据
        open_frame, exchange_frame, money_frame = await fetch_rank_frames()
        # 2.归一化为可入库记录
        fetched_at = datetime.now()
        open_rows = self._to_latest_rows(open_frame, fetched_at=fetched_at)
        exchange_rows = self._to_latest_rows(exchange_frame, fetched_at=fetched_at)
        money_rows = self._to_latest_rows(money_frame, fetched_at=fetched_at)
        # 3.存储入库
        return await self.save(open_rows, exchange_rows, money_rows)

    @staticmethod
    def _to_latest_rows(
        rows: list[dict[str, Any]],
        *,
        fetched_at: datetime,
    ) -> list[dict[str, Any]]:
        return [
            {
                **raw,
                "data_date": normalize_date(raw.get("data_date")),
                "fetched_at": fetched_at,
            }
            for raw in rows
        ]

    async def save(
        self,
        open_rows: list[dict[str, Any]],
        exchange_rows: list[dict[str, Any]],
        money_rows: list[dict[str, Any]],
    ) -> dict[str, int]:
        # 1. 收集所有基金代码，查询 Fund 表获取 fund_id 映射
        all_codes = sorted(
            set(
                [r["fund_code"] for r in open_rows]
                + [r["fund_code"] for r in exchange_rows]
                + [r["fund_code"] for r in money_rows]
            )
        )
        result = await self.db.execute(select(Fund.id, Fund.code).where(Fund.code.in_(all_codes)))
        fund_ids = {code: fund_id for fund_id, code in result.all()}
        if len(fund_ids) != len(all_codes):
            # 检查是否有缺失的基金代码 缺失原因是可能有新发基金，基金主表未同步但排行存在
            missing = sorted(set(all_codes) - set(fund_ids))
            logger.warning("Fund 表中缺少 %d 个基金代码，已跳过: %s", len(missing), missing[:10])
            # 剔除缺失基金的记录，继续处理
            open_rows = [r for r in open_rows if r["fund_code"] in fund_ids]
            exchange_rows = [r for r in exchange_rows if r["fund_code"] in fund_ids]
            money_rows = [r for r in money_rows if r["fund_code"] in fund_ids]

        # 2. 将各个类型排行榜数据进行入库
        logger.info(
            f"开始入库 open: {len(open_rows)} 条, exchange: {len(exchange_rows)} 条, money: {len(money_rows)} 条",
        )
        await self._replace_latest(FundOpenRankLatest, open_rows, fund_ids)
        await self._replace_latest(FundExchangeRankLatest, exchange_rows, fund_ids)
        await self._replace_latest(FundMoneyRankLatest, money_rows, fund_ids)

    async def _replace_latest(
        self,
        model: type[FundOpenRankLatest] | type[FundExchangeRankLatest] | type[FundMoneyRankLatest],
        rows: list[dict[str, Any]],
        fund_ids: dict[str, int],
    ) -> None:
        """全量替换并同步特定的基金排行榜表并清理那些不在新数据中的旧记录"""
        if not rows:
            return
        values = [{**row, "fund_id": fund_ids[row["fund_code"]]} for row in rows]
        update_columns = [key for key in values[0] if key not in {"fund_code", "created_at"}]
        try:
            # 分批 Upsert（插入或更新）
            for batch in iter_batches(values):
                statement = pg_insert(model).values(batch)
                await self.db.execute(
                    statement.on_conflict_do_update(
                        index_elements=[model.fund_code],
                        set_={column: getattr(statement.excluded, column) for column in update_columns},
                    )
                )
            # 数据清理（删除过时记录）
            current_codes = [row["fund_code"] for row in rows]
            await self.db.execute(delete(model).where(model.fund_code.not_in(current_codes)))
        except Exception as exc:
            logger.exception(
                f"{model.__tablename__} 入库失败: rows={len(rows)}, "
                f"样本keys={list(values[0].keys()) if values else []}, 异常={exc}"
            )
            raise
