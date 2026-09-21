"""Agent Worker 使用的 LangGraph 状态图定义。"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.services.agent.state import AgentState


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
    """支持工具调用的 Agent 图。

        图结构：
            START → agent ─┬─(有 tool_calls)→ tools → agent → ...
                           └─(无 tool_calls)→ END

        关键要点：
        1. llm 必须先 bind_tools，模型才会输出 tool_calls
        2. ToolNode 是 LangGraph 内置的，自动执行工具 + 生成 ToolMessage
        3. 条件边判断最后一条 AI 消息有没有 tool_calls
        4. agent→tools→agent 形成循环，但需要 max_tool_calls 熔断
           （LangGraph 推荐用消息数或单独字段来防死循环）
    """
    llm_with_tools = llm.bind_tools(tools)

    # ---- Agent 节点：让 LLM 思考并回复 ----
    async def agent_node(state: AgentState) -> dict:
        """调用绑定了工具的 LLM。返回值只写增量字段。"""
        messages = [SystemMessage(content=system_prompt), *state["messages"]]
        response = await llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    # ---- Tool 节点：LangGraph 内置，不需要自己写 ----
    # ToolNode(tools) 会：
    # 1. 从最后一条 AIMessage 里提取 tool_calls
    # 2. 依次调用工具（支持并发）
    # 3. 把结果包装成 ToolMessage 追加到 state.messages
    tool_node = ToolNode(tools)

    # ---- 条件边：判断要不要调用工具 ----
    def should_continue(state: AgentState) -> str:
        last_message = state["messages"][-1]

        # 模型没输出 tool_calls → 正常对话结束
        if not last_message.tool_calls:
            return END

        # 熔断保护：统计带 tool_calls 的 AIMessage 数量（每次 agent 输出算一轮）
        # 超过 max_tool_calls 强制结束，避免 ReAct 死循环
        call_rounds = sum(1 for m in state["messages"] if getattr(m, "tool_calls", None))

        if call_rounds > state.get("max_tool_calls", 5):
            return END

        return "tools"

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tool_node)

    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",  # 有 tool_calls -> 去执行工具
            END: END,  # 没有 -> 结束
        },
    )
    builder.add_edge("tools", "agent")  # 工具执行完回到 agent, 让模型根据结果生成自然语言回答

    return builder.compile(checkpointer=checkpointer)
