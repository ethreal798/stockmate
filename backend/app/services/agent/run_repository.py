"""AgentRun 及其关联实体（AgentMessage、AgentThread）的持久化层。

只做 DB 读写 + 状态机转换，不做业务决策（比如"要不要熔断"不在这）。
Worker 和 Executor 都通过这个类操作 AgentRun。
"""

import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update

from app.config import settings
from app.core.database import async_session_factory
from app.models.agent import AgentMessage, AgentRun, AgentThread

logger = logging.getLogger(__name__)


class AgentRunRepository:
    """AgentRun 及关联实体的状态持久化。

    方法按生命周期分组：
    - 进度快照：save_progress
    - 终态写入：finish_completed / finish_failed / finish_canceled
    - 辅助：store_terminal_event_id
    - 租约收割：interrupt_stale_runs
    """

    # ------------------------------------------------------------------
    # 进度快照（周期性调用，刷新租约 + 写 partial content）
    # ------------------------------------------------------------------

    async def save_progress(self, run_id: UUID, content: str, last_event_id: str | None) -> bool:
        """保存部分回复、刷新 Worker 租约，并返回是否收到中断请求。

        Returns:
            True if the run was canceled (run.status == "cancel_requested").
        """
        async with async_session_factory() as db:
            async with db.begin():
                # 加行锁，确保在事务中读取到的是最新数据
                run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id).with_for_update())).scalar_one()
                # 1. 快照：把累积的回复存进 Run
                run.content_snapshot = content
                # 2. 存 SSE 游标（断线续传用）
                run.last_event_id = last_event_id or run.last_event_id
                # 3. 续租：声明"我还活着"
                run.lease_expires_at = datetime.now() + timedelta(seconds=settings.AGENT_RUN_LEASE_SECONDS)
                # 4. 助手消息同步更新
                message = (
                    await db.execute(select(AgentMessage).where(AgentMessage.id == run.assistant_message_id))
                ).scalar_one()
                message.content = content
                # 5. 检查是否收到中断请求
                return run.status == "cancel_requested"

    # ------------------------------------------------------------------
    # 终态写入
    # ------------------------------------------------------------------

    async def finish_completed(
        self,
        run_id: UUID,
        *,
        content: str,
        last_event_id: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
        model_name: str,
        finish_reason: str,
        citations: list[dict] | None = None,
    ) -> str:
        """在同一事务中完成 Run、助手消息和会话 Token 统计。

        Returns:
            最终状态字符串："completed" 或 "canceled"（如果中途收到了取消请求）。
        """
        async with async_session_factory() as db:
            async with db.begin():
                run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id).with_for_update())).scalar_one()
                if run.status == "cancel_requested":
                    await self._apply_canceled(db, run, content, last_event_id)
                    return "canceled"
                run.status = "completed"
                run.content_snapshot = content
                run.last_event_id = last_event_id or run.last_event_id
                run.model_name = model_name
                run.finish_reason = finish_reason
                run.input_tokens = input_tokens
                run.output_tokens = output_tokens
                total_tokens = (input_tokens or 0) + (output_tokens or 0)
                run.total_tokens = total_tokens
                run.finished_at = datetime.now()
                run.lease_expires_at = None
                message = (
                    await db.execute(select(AgentMessage).where(AgentMessage.id == run.assistant_message_id))
                ).scalar_one()
                message.content = content
                message.status = "completed"
                message.model_name = model_name
                message.finish_reason = finish_reason
                message.input_tokens = input_tokens
                message.output_tokens = output_tokens
                message.total_tokens = total_tokens
                message.citations = citations
                thread = (
                    await db.execute(select(AgentThread).where(AgentThread.id == run.thread_id).with_for_update())
                ).scalar_one()
                thread.total_input_tokens = (thread.total_input_tokens or 0) + (input_tokens or 0)
                thread.total_output_tokens = (thread.total_output_tokens or 0) + (output_tokens or 0)
                thread.last_message_at = datetime.now()
                return "completed"

    async def finish_canceled(self, run_id: UUID, content: str, last_event_id: str | None) -> None:
        """持久化任务已取消状态。"""
        async with async_session_factory() as db:
            async with db.begin():
                run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id).with_for_update())).scalar_one()
                await self._apply_canceled(db, run, content, last_event_id)

    async def _apply_canceled(self, db, run: AgentRun, content: str, last_event_id: str | None) -> None:
        """把取消状态同时应用到 Run 和助手消息。

        内部方法：被 finish_completed 和 finish_canceled 复用。
        """
        run.status = "canceled"
        run.content_snapshot = content
        run.last_event_id = last_event_id or run.last_event_id
        run.finish_reason = "abort"
        run.finished_at = datetime.now()
        run.lease_expires_at = None
        message = (
            await db.execute(select(AgentMessage).where(AgentMessage.id == run.assistant_message_id))
        ).scalar_one()
        message.content = content
        message.status = "canceled"
        message.finish_reason = "abort"

    async def finish_failed(
        self,
        run_id: UUID,
        content: str,
        last_event_id: str | None,
        error_message: str,
    ) -> None:
        """持久化任务失败信息和已经生成的部分内容。"""
        async with async_session_factory() as db:
            async with db.begin():
                run = (
                    await db.execute(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
                ).scalar_one_or_none()
                if run is None or run.status in ("completed", "canceled"):
                    return
                run.status = "failed"
                run.content_snapshot = content
                run.last_event_id = last_event_id or run.last_event_id
                run.finish_reason = "error"
                run.error_message = error_message
                run.finished_at = datetime.now()
                run.lease_expires_at = None
                message = (
                    await db.execute(select(AgentMessage).where(AgentMessage.id == run.assistant_message_id))
                ).scalar_one()
                message.content = content
                message.status = "failed"
                message.finish_reason = "error"
                message.error_message = error_message

    # ------------------------------------------------------------------
    # SSE 游标存储
    # ------------------------------------------------------------------

    async def store_terminal_event_id(self, run_id: UUID, event_id: str) -> None:
        """保存终态事件 ID，供 SSE 重连时建立游标。"""
        async with async_session_factory() as db:
            async with db.begin():
                await db.execute(update(AgentRun).where(AgentRun.id == run_id).values(last_event_id=event_id))

    # ------------------------------------------------------------------
    # 租约收割
    # ------------------------------------------------------------------

    async def interrupt_stale_runs(self) -> None:
        """把租约过期的运行中任务标记为 interrupted，避免静默卡死。"""
        now = datetime.now()
        async with async_session_factory() as db:
            async with db.begin():
                stale = (
                    (
                        await db.execute(
                            select(AgentRun).where(
                                AgentRun.status.in_(("running", "cancel_requested")),
                                AgentRun.lease_expires_at.is_not(None),
                                AgentRun.lease_expires_at < now,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for run in stale:
                    run.status = "interrupted"
                    run.finish_reason = "worker_restart"
                    run.error_message = "Agent worker stopped before the run completed"
                    run.finished_at = now
                    run.lease_expires_at = None
                    message = (
                        await db.execute(select(AgentMessage).where(AgentMessage.id == run.assistant_message_id))
                    ).scalar_one()
                    message.status = "failed"
                    message.error_message = run.error_message
                if stale:
                    logger.warning(
                        "Reaped %d stale runs (lease expired before completion)",
                        len(stale),
                    )
