"""独立执行 LangGraph Agent 后台任务的 Worker 进程。
python -m app.workers.agent_run_worker

职责：
1. 进程生命周期（初始化 Checkpointer、Redis、数据库、信号处理）
2. 轮询领取待执行任务 → 调 Executor 执行 → 调 Repository 持久化
3. Worker 只管"什么时候做"，Executor 管"怎么做"
"""

import asyncio
import logging
import os
import socket
import sys
import time
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import settings
from app.core.database import async_session_factory, close_db
from app.core.logging import setup_logging
from app.core.redis import close_redis
from app.services.agent.agent_service import claim_next_run
from app.services.agent.executor import AgentRunExecutor
from app.services.agent.llm_factory import LLMFactory
from app.services.agent.run_repository import AgentRunRepository

logger = logging.getLogger(__name__)


class AgentRunWorker:
    """轮询、执行并持久化 Agent Run，且不依赖客户端 SSE 连接。

    分层：
    - 本类（Worker）：进程生命周期、轮询循环、任务领取
    - executor.py：LangGraph 组装 + 流式执行 + chunk 解析
    - run_repository.py：DB 持久化（状态机转换、租约收割）
    """

    def __init__(self) -> None:
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self.repository = AgentRunRepository()
        self.executor = AgentRunExecutor(
            llm_factory=LLMFactory(),
            repository=self.repository,
        )
        self._stopping = False

    async def run_forever(self) -> None:
        """初始化 Checkpointer，并持续领取数据库中的待执行任务。"""
        await self.repository.interrupt_stale_runs()
        checkpoint_url = self._checkpoint_url()
        async with AsyncPostgresSaver.from_conn_string(checkpoint_url) as checkpointer:
            await checkpointer.setup()
            logger.info(
                "Agent worker started: worker_id=%s, checkpoint_url=%s",
                self.worker_id,
                checkpoint_url,
            )
            last_reap_at = time.monotonic()
            idle_ticks = 0
            while not self._stopping:
                if time.monotonic() - last_reap_at >= min(settings.AGENT_RUN_LEASE_SECONDS / 2, 30):
                    await self.repository.interrupt_stale_runs()
                    last_reap_at = time.monotonic()

                run_id = await self._claim()
                if run_id is None:
                    idle_ticks += 1
                    if idle_ticks % 20 == 0:
                        logger.debug("Agent worker idle: no pending runs (tick=%d)", idle_ticks)
                    await asyncio.sleep(settings.AGENT_RUN_POLL_SECONDS)
                    continue

                idle_ticks = 0
                logger.info("Claimed run: run_id=%s", run_id)
                await self.executor.execute(run_id, checkpointer)

    # ------------------------------------------------------------------
    # 任务领取
    # ------------------------------------------------------------------

    async def _claim(self) -> UUID | None:
        """在独立事务中原子领取一个待执行任务。"""
        async with async_session_factory() as db:
            async with db.begin():
                run = await claim_next_run(db, self.worker_id)
                return run.id if run is not None else None

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _checkpoint_url() -> str:
        """把 SQLAlchemy PostgreSQL URL 转换为 psycopg 可识别的连接串。"""
        url = settings.LANGGRAPH_DATABASE_URL or settings.DATABASE_URL
        return url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")


async def main() -> None:
    """启动 Worker，并在退出时释放 Redis 和数据库连接。"""
    setup_logging()
    worker = AgentRunWorker()
    try:
        await worker.run_forever()
    finally:
        await close_redis()
        await close_db()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
