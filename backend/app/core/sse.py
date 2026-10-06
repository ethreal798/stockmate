"""SSE (Server-Sent Events) 管理器。

用于向前端发送实时通知信号。
"""

import asyncio
import logging
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


class SseManager:
    """管理 SSE 连接，支持广播信号。"""

    def __init__(self) -> None:
        # 使用 set 存储所有活跃客户端的队列，避免重复并提高删除效率
        self._clients: set[asyncio.Queue] = set()
        # 引入锁保护对 _clients 的修改，确保并发安全
        self._lock = asyncio.Lock()

    async def subscribe(self) -> AsyncGenerator[str, None]:
        """前端调用该方法订阅 SSE 信号。"""
        queue = asyncio.Queue()
        async with self._lock:
            self._clients.add(queue)
            logger.info(f"New SSE client subscribed. Total clients: {len(self._clients)}")

        try:
            while True:
                # 等待信号
                message = await queue.get()
                yield f"data: {message}\n\n"
        except asyncio.CancelledError:
            # 如果在等消息期间，连接被取消了（比如前端关了页面、网络断了），就会抛出这个异常。
            logger.info("SSE client connection cancelled")
        finally:
            # 能走到这里说明发生异常了，所以必须从集合中移除异常队列
            async with self._lock:
                if queue in self._clients:
                    self._clients.remove(queue)
                    logger.info(f"SSE client unsubscribed. Total clients: {len(self._clients)}")

    async def broadcast(self, message: str) -> None:
        """向所有订阅者广播信号。"""
        # 广播时也需要获取锁，防止在遍历过程中集合被修改
        async with self._lock:
            if not self._clients:
                return

            logger.debug(f"Broadcasting SSE signal: {message} to {len(self._clients)} clients")
            # 批量将消息放入所有队列
            for queue in self._clients:
                await queue.put(message)


# 全局 SSE 管理器实例
sse_manager = SseManager()
