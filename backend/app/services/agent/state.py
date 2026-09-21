from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Agent 运行时的全局状态"""

    # 基础必须字段
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: int
    thread_id: str
    model_config_id: int
    capability: str

    # 工具调用相关
    # agent 节点每次调用工具时 +1，超过阈值直接走 END 避免无限循环
    max_tool_calls: int
    # tool_results: list[dict]

    # RAG 相关
    # retrieved_docs: list[dict]
    # retrieval_query: str | None

    # 记忆相关
    # conversation_summary: str | None
    # user_profile: dict | None
