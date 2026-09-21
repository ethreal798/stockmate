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
