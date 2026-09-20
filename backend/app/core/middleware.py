"""统一响应格式中间件。

将所有 HTTP API 响应包装为 {code, msg, data} 格式。
特殊响应类型（SSE、WebSocket）会被跳过包装。

使用纯 ASGI 中间件实现，避免 BaseHTTPMiddleware 的 body_iterator 问题。

潜在问题
1. ApiResponse.success(data=data) 可能丢失原始状态码
2. body_bytes += body 对大请求可能内存爆炸
"""

import json
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send


def is_already_wrapped(data: Any) -> bool:
    """检查数据是否已经是 ApiResponse 格式。

    判断规则：必须同时包含 code、msg、data 三个字段
    且 code 为 0 或 1，msg 为字符串类型。
    这样可以避免误判业务数据中的 code 字段（如基金代码、股票代码等）。
    """
    if not isinstance(data, dict):
        return False
    # 精确判断：code 是整数且为 0 或 1，msg 存在且为字符串
    if "code" in data and "msg" in data and "data" in data:
        if isinstance(data["code"], int) and data["code"] in (0, 1):
            if isinstance(data["msg"], str):
                return True
    return False


class ResponseWrapperMiddleware:
    """统一响应包装的 ASGI 中间件。

    自动将所有 HTTP API 响应包装为 {code, msg, data} 格式，
    但跳过以下特殊场景：
    - SSE 流式响应 (content-type: text/event-stream)
    - 文件下载 (content-type: application/octet-stream)
    - WebSocket 升级响应 (HTTP 101)
    - 异常处理器返回的已包装错误响应
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    # FastAPI 内置的 schema / 文档端点，这些响应不应被统一包装
    _SKIP_PATHS = frozenset(
        {
            "/openapi.json",
            "/openapi.yaml",
            "/docs",
            "/docs/",
            "/docs/oauth2-redirect",
            "/redoc",
            "/redoc/",
        }
    )

    # FastAPI 内置的 schema / 文档端点，这些响应不应被统一包装
    _SKIP_PATHS = frozenset(
        {
            "/openapi.json",
            "/openapi.yaml",
            "/docs",
            "/docs/",
            "/docs/oauth2-redirect",
            "/redoc",
            "/redoc/",
        }
    )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # 只处理 HTTP 请求
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 跳过 FastAPI 内置的 OpenAPI schema 和文档端点
        path = scope.get("path", "")
        if path in self._SKIP_PATHS:
            await self.app(scope, receive, send)
            return

        # 检查是否是 FastAPI 内置的 schema / 文档端点
        if scope["path"] in self._SKIP_PATHS:
            await self.app(scope, receive, send)
            return

        # 存储响应信息
        status_code = None
        response_headers = []
        body_bytes = b""
        skip_wrapping = False
        start_sent = False

        async def send_with_wrapping(message):
            nonlocal status_code, response_headers, body_bytes, skip_wrapping, start_sent

            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = message.get("headers", [])

                # 检查是否需要跳过包装
                if status_code == 101:
                    skip_wrapping = True
                else:
                    content_type = self._get_content_type(response_headers)
                    if "text/event-stream" in content_type or "application/octet-stream" in content_type:
                        skip_wrapping = True

                # 只有在跳过包装时才立即发送 start 消息
                if skip_wrapping:
                    await send(message)
                    start_sent = True

            elif message["type"] == "http.response.body":
                if skip_wrapping:
                    # 直接转发
                    await send(message)
                    return

                # 收集 body 数据
                body = message.get("body", b"")
                body_bytes += body

                if not message.get("more_body", False):
                    # 所有 body 数据收集完成
                    try:
                        data = json.loads(body_bytes) if body_bytes else None

                        if not is_already_wrapped(data) and data is not None:
                            # 执行包装
                            from app.core.response import ApiResponse

                            wrapped = ApiResponse.success(data=data)
                            new_body = wrapped.model_dump_json().encode("utf-8")

                            # 如果 start 还没发送，发送新的 start
                            if not start_sent:
                                new_headers = [
                                    (b"content-type", b"application/json"),
                                    (b"content-length", str(len(new_body)).encode("utf-8")),
                                ]
                                # 保留原始 headers 中重要的字段（如 set-cookie）
                                for key, value in response_headers:
                                    if isinstance(key, bytes):
                                        key_str = key.decode("utf-8")
                                    else:
                                        key_str = key
                                    key_lower = key_str.lower()
                                    if key_lower not in ("content-type", "content-length", "transfer-encoding"):
                                        if isinstance(key, str):
                                            key = key.encode("utf-8")
                                        if isinstance(value, str):
                                            value = value.encode("utf-8")
                                        new_headers.append((key, value))

                                await send(
                                    {
                                        "type": "http.response.start",
                                        "status": status_code,
                                        "headers": new_headers,
                                    }
                                )
                                start_sent = True

                            # 发送包装后的 body
                            await send(
                                {
                                    "type": "http.response.body",
                                    "body": new_body,
                                }
                            )
                            return
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        # 非 JSON 响应，不包装
                        pass

                    # 如果没有执行包装，需要先发送 start（如果还没发送）
                    if not start_sent:
                        await send(
                            {
                                "type": "http.response.start",
                                "status": status_code,
                                "headers": response_headers,
                            }
                        )
                        start_sent = True

                    # 发送原始 body
                    await send(message)

        # 调用应用
        await self.app(scope, receive, send_with_wrapping)

    def _get_content_type(self, headers: list) -> str:
        """从 headers 列表中获取 content-type。"""
        for key, value in headers:
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            if key_str.lower() == "content-type":
                return value.decode("utf-8") if isinstance(value, bytes) else value
        return ""
