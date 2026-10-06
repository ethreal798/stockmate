"""大模型调用服务。"""

from typing import Any

import httpx

from app.config import settings


class LLMService:
    """OpenAI 兼容 chat completions 调用封装。"""

    async def generate(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """调用聊天模型生成回答。

        Args:
            messages: 对话消息列表。
            model: 模型名，默认用 settings.AI_MODEL_NAME。
            temperature: 采样温度，默认用 settings.AI_TEMPERATURE。
            max_tokens: 最大输出 token，默认用 settings.AI_MAX_TOKENS。
            response_format: 结构化输出格式（如 {"type": "json_object"}），
                qwen3.8 / deepseek 等部分模型原生支持。
            extra_params: 提供商特有的额外参数，如 qwen3.8 的
                enable_thinking=False（关闭隐藏思考链，省 ~90% output token）。
        """
        model_name = model or settings.AI_MODEL_NAME
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": settings.AI_TEMPERATURE if temperature is None else temperature,
            "max_tokens": max_tokens or settings.AI_MAX_TOKENS,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if extra_params:
            payload.update(extra_params)

        headers = {"Content-Type": "application/json"}

        if settings.AI_API_KEY:
            headers["Authorization"] = f"Bearer {settings.AI_API_KEY}"

        url = f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()

        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {
            "content": content,
            "model": data.get("model", model_name),
            "usage": data.get("usage"),
        }
