"""工具共享的依赖上下文。

设计原则：工具需要调 db 时自己从 async_session_factory 租 session，
用完立刻还（Lazy acquire，用完即还），不提前持有连接。
ToolContext 只存业务层参数（user_id 等）。
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolContext:
    user_id: int | None = None
    extra: dict[str, Any] | None = None
