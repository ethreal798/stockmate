"""工具结果通用处理函数。

和 fund_tools.py 里格式化逻辑的分工：

- utils.py：纯文本操作（截断、清洗），所有工具都能复用

- fund_tools.py：基金领域特定的格式化（字段选择、标签拼接）
"""

def truncate_result(text: str, max_length: int = 2000) -> str:
    """截断过长的工具结果，避免撑爆 LLM 上下文窗口。

    Args:
        text: 原始工具返回文本
        max_length: 保留的最大字符数（含截断提示）

    Returns:
        截断后的文本，带省略提示；未超限时原样返回
    """
    if not text or len(text) <= max_length:
        return text
    return text[:max_length] + f"\n\n...（已截断，原始长度 {len(text)} 字符）"
