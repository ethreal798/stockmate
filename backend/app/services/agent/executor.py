"""单个 AgentRun 的 LangGraph 执行器。

职责：
1. 读取任务元数据（run / user_message / model_config / system_prompt）
2. 组装 LangGraph 图（general vs tool capability 分流）
3. 用 graph.astream(stream_mode="messages") 流式执行
4. 每帧解析 chunk（content / model_name / usage / finish_reason）
5. 周期性调用 repository.save_progress 做快照 + 续租 + 取消检查
6. 正常完成 → repository.finish_completed；异常 → repository.finish_failed；中途取消 → finish_canceled
7. 全程通过 event_stream 发布 SSE 事件

Worker 只管"什么时候执行"（轮询循环），Executor 管"怎么执行"。
"""

import logging
import time
from typing import Any
from uuid import UUID

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy import select

from app.config import settings
from app.core.database import async_session_factory
from app.models.agent import AgentMessage, AgentRun
from app.services.agent.event_stream import AgentEventStream
from app.services.agent.graph import build_general_chat_graph, build_tool_chat_graph
from app.services.agent.llm_factory import LLMFactory
from app.services.agent.prompt_template_service import PromptTemplateService
from app.services.agent.run_repository import AgentRunRepository
from app.services.agent.runtime_model_config_service import RuntimeModelConfigService
from app.services.agent.tools import get_all_tools
from app.services.agent.tools.base import ToolContext

logger = logging.getLogger(__name__)


class AgentRunExecutor:
    """单个 AgentRun 的完整执行生命周期。

    依赖（通过构造函数注入，方便测试）：
    - llm_factory: 创建 LLM 客户端
    - repository: AgentRun 状态持久化
    """

    def __init__(self, llm_factory: LLMFactory, repository: AgentRunRepository) -> None:
        self.llm_factory = llm_factory
        self.repository = repository

    async def execute(self, run_id: UUID, checkpointer: BaseCheckpointSaver) -> None:
        """执行单个 Run：组装图 → 流式执行 → 持久化终态 + 发布事件。"""
        from app.core.redis import get_redis

        redis = await get_redis()
        events = AgentEventStream(redis)
        content_parts: list[str] = []
        usage: dict[str, Any] | None = None
        model_name: str | None = None
        finish_reason: str | None = None
        last_event_id: str | None = None
        last_snapshot_at = time.monotonic()

        try:
            # 1. 读任务元数据（只在任务开始时读一次，随后释放 DB 连接）
            async with async_session_factory() as db:
                run = (
                    await db.execute(select(AgentRun).where(AgentRun.id == run_id))
                ).scalar_one()
                user_message = (
                    await db.execute(
                        select(AgentMessage).where(AgentMessage.id == run.user_message_id)
                    )
                ).scalar_one()
                model_config = await RuntimeModelConfigService(db).resolve(
                    run.user_id, run.model_config_id
                )
                system_prompt = (
                    await PromptTemplateService(db).get_general_chat_system_prompt()
                )

            # 2. 组装 LangGraph 图（根据 capability 分流）
            llm = self.llm_factory.create_chat_model(model_config, streaming=True)
            graph = self._build_graph(
                run=run, llm=llm, system_prompt=system_prompt, checkpointer=checkpointer
            )

            config = {
                "configurable": {
                    "thread_id": str(run.thread_id),
                    "run_id": str(run.id),
                }
            }
            await events.publish(
                run_id, "metadata", {"run_id": str(run_id), "status": "running"}
            )

            logger.info(
                "Executing graph: run_id=%s thread_id=%s user_id=%s model=%s msg_len=%d",
                run_id, run.thread_id, run.user_id, model_config.model, len(user_message.content),
            )

            # 3. 流式执行 + 周期性快照
            async for chunk, _metadata in graph.astream(
                {
                    "messages": [HumanMessage(content=user_message.content)],
                    "user_id": run.user_id,
                    "thread_id": str(run.thread_id),
                    "model_config_id": run.model_config_id,
                    "capability": run.capability,
                    "max_tool_calls": 5,
                    "tool_call_count": 0,
                },
                config=config,
                stream_mode="messages",
            ):
                # 跳过内部 ToolMessage
                if isinstance(chunk, ToolMessage):
                    continue

                # 解析 chunk 元数据（可能为空，因为不是最终帧）
                model_name = self._extract_model_name(chunk) or model_name
                chunk_usage = getattr(chunk, "usage_metadata", None)
                if chunk_usage:
                    usage = dict(chunk_usage)
                response_metadata = getattr(chunk, "response_metadata", None) or {}
                finish_reason = (
                    response_metadata.get("finish_reason") or finish_reason
                )

                content = self._normalize_content(getattr(chunk, "content", ""))
                if content:
                    content_parts.append(content)
                    last_event_id = await events.publish(
                        run_id, "delta", {"content": content}
                    )

                # 周期性快照 + 续租 + 感知取消请求
                now = time.monotonic()
                if now - last_snapshot_at >= settings.AGENT_SNAPSHOT_INTERVAL_SECONDS:
                    canceled = await self.repository.save_progress(
                        run_id, "".join(content_parts), last_event_id
                    )
                    last_snapshot_at = now
                    if canceled:
                        logger.info("Run canceled via snapshot check: run_id=%s", run_id)
                        await self.repository.finish_canceled(
                            run_id, "".join(content_parts), last_event_id
                        )
                        terminal_id = await events.publish(
                            run_id,
                            "aborted",
                            {"run_id": str(run_id), "status": "canceled"},
                        )
                        await self.repository.store_terminal_event_id(
                            run_id, terminal_id
                        )
                        return

            # 4. 正常完成
            content = "".join(content_parts)
            input_tokens, output_tokens, _ = self._parse_usage(usage)
            final_status = await self.repository.finish_completed(
                run_id,
                content=content,
                last_event_id=last_event_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model_name=model_name or model_config.model,
                finish_reason=finish_reason or "stop",
            )
            logger.info(
                "Run finished: run_id=%s status=%s finish_reason=%s model=%s usage=%s",
                run_id, final_status, finish_reason or "stop",
                model_name or model_config.model, usage,
            )
            terminal_event = "aborted" if final_status == "canceled" else "done"
            terminal_id = await events.publish(
                run_id,
                terminal_event,
                {
                    "run_id": str(run_id),
                    "status": final_status,
                    "model_name": model_name or model_config.model,
                    "usage": usage,
                },
            )
            await self.repository.store_terminal_event_id(run_id, terminal_id)
        except Exception as exc:
            # 执行异常 → 持久化失败 + 发布 error 事件
            logger.exception("Agent run failed: run_id=%s", run_id)
            await self.repository.finish_failed(
                run_id, "".join(content_parts), last_event_id,
                str(exc) or "Agent run failed",
            )
            try:
                event_id = await events.publish(
                    run_id,
                    "error",
                    {
                        "run_id": str(run_id),
                        "status": "failed",
                        "message": str(exc) or "Agent run failed",
                    },
                )
                await self.repository.store_terminal_event_id(run_id, event_id)
            except Exception:
                logger.exception(
                    "Failed to publish terminal error event: run_id=%s", run_id
                )

    # ------------------------------------------------------------------
    # 内部：图组装
    # ------------------------------------------------------------------

    @staticmethod
    def _build_graph(*, run, llm, system_prompt, checkpointer: BaseCheckpointSaver):
        """根据 run.capability 选对应图构建器。"""
        if run.capability == "general":
            return build_general_chat_graph(
                llm=llm, system_prompt=system_prompt, checkpointer=checkpointer
            )
        # 带工具
        tool_ctx = ToolContext(user_id=run.user_id)
        tools = get_all_tools(tool_ctx)
        return build_tool_chat_graph(
            llm=llm, system_prompt=system_prompt, checkpointer=checkpointer, tools=tools
        )

    # ------------------------------------------------------------------
    # 流式 chunk 解析工具（留在 executor 内部，不单独文件）
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_content(content: Any) -> str:
        """兼容字符串和多模态内容块，提取可展示文本。"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "".join(parts)
        return str(content) if content is not None else ""

    @staticmethod
    def _extract_model_name(chunk: Any) -> str | None:
        """从不同兼容服务的响应元数据中提取模型名称。"""
        metadata = getattr(chunk, "response_metadata", None) or {}
        return metadata.get("model_name") or metadata.get("model")

    @staticmethod
    def _parse_usage(usage: dict[str, Any] | None) -> tuple[int | None, int | None, int | None]:
        """兼容 LangChain 与 OpenAI 风格的 Token 用量字段。"""
        if not usage:
            return None, None, None
        input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
        output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
        total_tokens = usage.get("total_tokens")
        if total_tokens is None and (input_tokens is not None or output_tokens is not None):
            total_tokens = (input_tokens or 0) + (output_tokens or 0)
        return input_tokens, output_tokens, total_tokens
