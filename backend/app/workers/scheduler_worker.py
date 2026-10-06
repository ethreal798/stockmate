"""Standalone APScheduler process for recurring background jobs.
python -m app.workers.scheduler_worker
"""

import asyncio
import logging
import signal
import sys

from app.core.database import close_db
from app.core.logging import setup_logging
from app.core.redis import close_redis
from app.services.scheduler_service import get_registered_jobs, scheduler_service

logger = logging.getLogger(__name__)

"""
监听信号：
SIGINT：通常是用户按下 Ctrl+C 触发。
SIGTERM：通常是 Docker 容器停止、Kubernetes Pod 删除或系统 kill 命令触发。
逻辑：一旦收到这两个信号中的任意一个，就会调用 stop_event.set()，这将唤醒后续的 await stop_event.wait()，从而触发清理流程。
兼容性：try-except 块处理了不同操作系统（Windows vs Linux/Mac）对异步信号处理的支持差异。
"""


async def main() -> None:
    """Register recurring jobs and run until the process receives a stop signal."""
    # 日志配置：setup_logging() 初始化日志系统，确保后续的 print 或 logger.info 能正确输出格式化日志。
    setup_logging()
    # 停止信号：创建一个 asyncio.Event() 对象。这是一个信号量，用于通知主循环何时停止。
    stop_event = asyncio.Event()
    # 事件循环：获取当前运行的事件循环，用于注册信号处理器。
    loop = asyncio.get_running_loop()

    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            # 尝试直接添加信号处理器 (适用于 Unix-like 系统)
            loop.add_signal_handler(signal_name, stop_event.set)
        except (NotImplementedError, RuntimeError):
            # 如果不支持（如 Windows 或部分环境），回退到线程安全的方式设置
            signal.signal(signal_name, lambda *_args: loop.call_soon_threadsafe(stop_event.set))

    # 导入任务模块，触发 @register_task 装饰器注册
    import app.services.scheduler.tasks  # noqa: F401

    scheduler_service.start()
    for job in get_registered_jobs():
        await scheduler_service.add_job(**job)
    logger.info("Scheduler worker ready: jobs=%s", [job["job_id"] for job in get_registered_jobs() if job["enabled"]])

    try:
        await stop_event.wait()
    finally:
        logger.info("Scheduler worker shutting down")
        scheduler_service.shutdown(wait=False)
        await close_redis()
        await close_db()


if __name__ == "__main__":
    if sys.platform == "win32":
        # Windows 兼容性：asyncio 在 Windows 上的默认事件循环策略在某些场景（如涉及子进程）下有限制。
        # 这里显式设置为 WindowsSelectorEventLoopPolicy 以确保在 Windows 开发环境下能正常运行。
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
