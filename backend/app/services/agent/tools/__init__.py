"""Agent 工具注册中心。

⚠️ 重点：所有工具模块都从这里导出，Worker 和 Graph 只依赖这一层，
后续加新工具只需在这里 import + register。
"""

from langchain_core.tools import BaseTool

from app.services.agent.tools.base import ToolContext
from app.services.agent.tools.fund_tools import create_fund_tools


def get_all_tools(context: ToolContext) -> list[BaseTool]:
    """根据 ToolContext 创建所有已注册的工具实例"""
    tools: list[BaseTool] = []
    tools.extend(create_fund_tools(context))

    return tools


__all__ = ["ToolContext", "get_all_tools"]
