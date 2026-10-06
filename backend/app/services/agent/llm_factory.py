"""根据用户模型配置创建 LangChain ChatModel。"""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from .runtime_model_config_service import RuntimeModelConfig


class LLMFactory:
    """为 OpenAI-compatible 服务创建统一的 LangChain 模型实例。"""

    def create_chat_model(self, config: RuntimeModelConfig, *, streaming: bool = True) -> BaseChatModel:
        """创建支持流式输出的 ChatOpenAI，并透传兼容服务的扩展参数。"""
        request_params = config.extra_config.get("request_params")
        explicit_params, model_kwargs = self._split_request_params(request_params)

        extra_body = config.extra_config.get("extra_body")
        default_headers = config.extra_config.get("default_headers")
        default_query = config.extra_config.get("default_query")
        max_retries = int(config.extra_config.get("max_retries", 2))
        stream_usage = bool(config.extra_config.get("stream_include_usage", False))

        kwargs: dict[str, Any] = {
            "model": config.model,
            "base_url": config.base_url,
            "api_key": config.api_key,
            "temperature": config.temperature,
            "max_tokens": config.max_output_tokens,
            "timeout": config.timeout_seconds,
            "streaming": streaming,
            "max_retries": max_retries,
            "model_kwargs": model_kwargs,
            "stream_usage": stream_usage,
        }

        if isinstance(extra_body, dict):
            kwargs["extra_body"] = extra_body
        if isinstance(default_headers, dict):
            kwargs["default_headers"] = default_headers
        if isinstance(default_query, dict):
            kwargs["default_query"] = default_query

        kwargs.update(explicit_params)
        return ChatOpenAI(**kwargs)

    @staticmethod
    def _split_request_params(request_params: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        """区分 ChatOpenAI 显式参数与需要放入 model_kwargs 的扩展参数。"""
        if not isinstance(request_params, dict):
            return {}, {}

        explicit_param_names = {
            "presence_penalty",
            "frequency_penalty",
            "seed",
            "logprobs",
            "top_logprobs",
            "logit_bias",
            "n",
            "top_p",
            "stop",
            "stop_sequences",
        }
        explicit_params: dict[str, Any] = {}
        model_kwargs: dict[str, Any] = {}
        for key, value in request_params.items():
            if key in explicit_param_names:
                explicit_params[key] = value
            else:
                model_kwargs[key] = value
        return explicit_params, model_kwargs
