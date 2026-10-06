"""速率限制模块 — 基于 slowapi + Redis。

为登录、注册等敏感接口提供分布式速率限制，
防止暴力破解和恶意注册。
"""

import logging
from typing import Optional

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.core.response import ApiResponse
from app.config import settings

logger = logging.getLogger(__name__)

# 全局限流器实例
_limiter: Optional[Limiter] = None


def get_limiter() -> Limiter:
    """获取全局限流器实例（懒加载）。

    使用 Redis 作为存储后端，支持分布式部署。

    注意：
    1. 通过 config_filename 阻止 slowapi 读取 .env 文件，
       避免 Windows 中文环境下因 gbk 编码导致的 UnicodeDecodeError。
       所有配置项已显式通过参数传入，无需从 .env 读取。
    2. storage_options 直接传递给 redis-py 的 ConnectionPool。
       redis 5.x 不支持 connection_pool_kwargs 嵌套结构，
       如需 Redis 客户端级别的 decode_responses 等配置，
       应通过 connection_pool 参数传入预构建的 ConnectionPool 实例。
       对于限流场景，默认配置已足够。
    """
    global _limiter
    if _limiter is None:
        _limiter = Limiter(
            key_func=get_remote_address,
            default_limits=[],
            storage_uri=settings.REDIS_URL,
            # 显式指定不存在的文件，阻止 slowapi 读取 .env
            # slowapi 默认会检查 .env 并以系统编码读取，
            # 在中文 Windows 下可能因 gbk 编码无法解码 UTF-8 文件导致报错终止程序
            config_filename=".slowapi_config",
        )
        logger.info("Rate limiter initialized with Redis backend")
    return _limiter


def create_rate_limit_middleware() -> SlowAPIMiddleware:
    """创建速率限制中间件。"""
    limiter = get_limiter()
    return SlowAPIMiddleware(limiter)


def get_rate_limit_exception_handler():
    """返回速率超限异常处理器。

    响应格式遵循全局 {code, msg, data} 统一格式，
    使 ResponseWrapperMiddleware 识别为已包装，避免二次包装。
    """
    from fastapi import Request
    from fastapi.responses import JSONResponse

    async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        logger.warning(
            "Rate limit exceeded: client=%s path=%s limit=%s",
            get_remote_address(request),
            request.url.path,
            exc.detail,
        )
        return JSONResponse(
            status_code=429,
            content=ApiResponse.error(
                msg="请求过于频繁，请稍后再试",
                data={"limit": str(exc.detail)},
            ).model_dump(),
        )

    return rate_limit_handler
