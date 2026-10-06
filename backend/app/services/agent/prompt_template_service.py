"""加载 Agent 提示词模板，并在模板缺失时提供默认值。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import PromptTemplate


class PromptTemplateService:
    """从数据库读取提示词模板。"""

    GENERAL_CHAT_SYSTEM = "general_chat_system"

    DEFAULT_GENERAL_CHAT_SYSTEM_PROMPT = (
        "你是一个中文 AI 助手，请用清晰、准确、克制的方式回答用户问题。"
        "涉及投资、医疗、法律等高风险内容时，提醒用户这不是专业建议。\n\n"
        "【当 search_news 等检索工具返回资料时，你必须遵守以下引用格式规则】\n\n"
        "工具返回的资料每一条以'资料 N:'开头，后面是来源、时间、标题、内容。"
        "你在回答中每引用一条资料，必须在对应的观点或事实末尾标注编号 [1] [2] [3]...\n\n"
        "规则：\n"
        "1. 资料编号和引用编号必须一一对应：资料 1 → 引用写 [1]，资料 2 → 引用写 [2]\n"
        "2. 一个观点用到多条资料时，依次标注如 [1][3]\n"
        "3. 所有事实性陈述都必须标注编号，不能遗漏\n"
        "4. 不确定或超出资料范围的内容不要编造\n\n"
        "示例：\n"
        "  资料：\n"
        "    资料 1: 来源：财联社；内容：壁仞科技今日涨近5%\n"
        "    资料 2: 来源：财联社；内容：黄仁勋称明年芯片销量将翻倍\n"
        "  正确回答：\n"
        "    港股 AI 股走强，壁仞科技涨近 5% [1]。英伟达 CEO 黄仁勋表示明年芯片销量将翻倍 [2]，"
        "这可能带动市场对 AI 基础设施的关注。\n"
        "  错误回答（缺少编号）：\n"
        "    港股 AI 股走强，壁仞科技涨近 5%。英伟达方面...\n"
    )

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_type(self, template_type: str, fallback: str = "") -> str:
        """返回指定类型最新的非空模板，不存在时返回 fallback。"""
        stmt = (
            select(PromptTemplate.content)
            .where(PromptTemplate.type == template_type)
            .order_by(PromptTemplate.updated_at.desc(), PromptTemplate.id.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        content = result.scalar_one_or_none()
        if content and content.strip():
            return content
        return fallback

    async def get_general_chat_system_prompt(self) -> str:
        """返回普通聊天使用的系统提示词。"""
        return await self.get_by_type(
            self.GENERAL_CHAT_SYSTEM,
            fallback=self.DEFAULT_GENERAL_CHAT_SYSTEM_PROMPT,
        )
