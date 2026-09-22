"""Agent Worker 使用的 LangGraph 状态图定义。"""

import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.services.agent.state import AgentState

logger = logging.getLogger(__name__)



def build_general_chat_graph(
    *,
    llm: BaseChatModel,
    system_prompt: str,
    checkpointer: BaseCheckpointSaver,
):
    """使用运行时选择的模型和 Checkpointer 编译普通聊天图。"""

    async def call_model(state: AgentState) -> dict:
        """把系统提示词和会话消息提交给 LangChain ChatModel。"""
        response = await llm.ainvoke([SystemMessage(content=system_prompt), *state["messages"]])
        return {"messages": [response]}

    # 当前仅有一个模型节点，后续工具、RAG 可以在这里扩展节点和条件边。
    builder = StateGraph(AgentState)
    builder.add_node("general_chat", call_model)
    builder.add_edge(START, "general_chat")
    builder.add_edge("general_chat", END)
    return builder.compile(checkpointer=checkpointer)


def build_tool_chat_graph(
    *,
    llm: BaseChatModel,
    system_prompt: str,
    checkpointer: BaseCheckpointSaver,
    tools: list[BaseTool],
):
    """支持工具调用的 Agent 图（ReAct 循环）。

        图结构：
            START → agent ──→ should_continue ──┬─(达到上限或无 tool_calls) → END
                                               └─(有 tool_calls) → increment_count → tools → agent → ...

        关键要点：
        1. llm.bind_tools() 让模型输出 tool_calls
        2. ToolNode 内置 handle_tool_errors=True：工具炸了自动包成 ToolMessage 返回给模型
        3. increment_count 独立节点：工具执行前 +1，职责单一
        4. should_continue 优先级：先查 tool_call_count 是否 ≥ max（熔断），再看 tool_calls（正常结束）
        5. 并行工具调用：tool_calls 是列表时一轮里调多个，但只算 1 次计数（防死循环语义是「轮次」不是「单次调用」）
    """
    llm_with_tools = llm.bind_tools(tools)

    # ---- Agent 节点：LLM 思考并回复 ----
    async def agent_node(state: AgentState) -> dict:
        messages = [SystemMessage(content=system_prompt), *state["messages"]]
        response = await llm_with_tools.ainvoke(messages)

        tool_calls = getattr(response, "tool_calls", None) or []
        if tool_calls:
            logger.info(
                "[agent_node] LLM 输出 %d 个 tool_calls (轮次=%d): %s",
                len(tool_calls), state.get("tool_call_count", 0),
                [(tc["name"], tc.get("args")) for tc in tool_calls],
            )

        return {"messages": [response]}

    # ---- 工具调用日志钩子 ----
    # 通过 awrap_tool_call 拦截每次工具调用，打日志但不干涉正常流程。
    # ToolNode 内置 handle_tool_errors=True 继续负责异常软着陆。
    async def _tool_logger(request, execute):
        tc = request.tool_call
        tool_name = tc["name"]
        logger.info("[tools] ▶ 执行: %s(args=%s)", tool_name, tc.get("args", {}))
        try:
            result = await execute(request)
            # handle_tool_errors 把异常转成 status="error" 的 ToolMessage
            is_error = getattr(result, "status", None) == "error"
            content_len = len(result.content) if result.content else 0
            if is_error:
                logger.warning(
                    "[tools] ✗ 工具报错: %s, 返回长度=%d, 错误=%s",
                    tool_name, content_len, (result.content or "")[:200],
                )
            else:
                logger.info("[tools] ✓ 完成: %s, 返回长度=%d", tool_name, content_len)
            return result
        except Exception as exc:
            # 理论上 handle_tool_errors 已兜底，这里 catch 是额外保险
            logger.exception("[tools] ✗ 未捕获异常: %s -> %s", tool_name, exc)
            raise

    # ---- Tool 节点 ----
    # ToolNode 自动：
    # 1. 从最后一条 AIMessage 提取 tool_calls
    # 2. 依次调用工具（支持并行）
    # 3. 把结果包装成 ToolMessage 追加到 state.messages
    # 4. handle_tool_errors=True：工具炸了自动包成 ToolMessage 返回给模型（不崩）
    # 5. awrap_tool_call=_tool_logger：每次工具调用打日志
    tool_node = ToolNode(
        tools,
        handle_tool_errors=True,
        awrap_tool_call=_tool_logger,
    )
    
    def increment_tool_count(state: AgentState) -> dict:
        current = state.get("tool_call_count", 0)
        return {"tool_call_count": current + 1}

    # ---- 条件边：先查熔断上限，再判断要不要调工具 ----
    def should_continue(state: AgentState) -> str:
        # 1. 先判断是否达到熔断上限
        count = state.get("tool_call_count", 0)
        max_calls = state.get("max_tool_calls", 5)
        if count >= max_calls:
            logger.warning("[should_continue] 触发熔断: tool_call_count=%d >= max=%d，强制结束", count, max_calls)
            return END

        # 2. 模型没输出 tool_calls -> 正常对话结束
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", None) or []
        if not (isinstance(last_message, AIMessage) and tool_calls):
            logger.debug("[should_continue] 无 tool_calls，正常结束 (已用 %d/%d 轮)", count, max_calls)
            return END

        logger.debug("[should_continue] 继续下一轮 ReAct (已用 %d/%d)", count, max_calls)
        return "increment_count"

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("increment_count", increment_tool_count)
    builder.add_node("tools", tool_node)

    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent",
        should_continue,
        {
            "increment_count": "increment_count",  # 有 tool_calls 且未超限 → 先计数
            END: END,  # 超限 或 无 tool_calls → 结束
        },
    )
    builder.add_edge("increment_count", "tools")  # 计数后执行工具
    builder.add_edge("tools", "agent")  # 工具执行完回到 agent, 让模型根据结果生成自然语言回答

    return builder.compile(checkpointer=checkpointer)
