from pydantic import BaseModel, Field


class SearchFundsInput(BaseModel):
    """搜索基金列表"""
    keyword: str = Field(
        description="基金代码（如'110022'）或基金名称（如'易方达蓝筹'）, 支持模糊匹配"
    )
    limit: int = Field(default=5, ge=1, le=20, description="最多返回多少只基金（1-20）")


class GetFundDetailInput(BaseModel):
    """查看单只基金的详细信息"""
    code: str = Field(description="基金代码，如'110022'")


class SearchNewsInput(BaseModel):
    """检索新闻资讯库（RAG）"""
    query: str = Field(description="检索关键词，如‘央行降息’ 、‘新能源板块’、‘A股行情’")
    top_k: int = Field(default=5, ge=0, le=10, description="返回的资讯数量（0-10）")
    days: int = Field(default=7, ge=1, le=60, description="只检索最近几天的资讯（1-60）默认7天")