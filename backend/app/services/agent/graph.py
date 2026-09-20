"""Agent Worker 使用的 LangGraph 状态图定义。"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
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
