from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    category: str = Field(
        default="all",
        description="검색 카테고리",
        pattern=r"^(all|marketing|tech|tools)$",
    )
    query: str = Field(
        description="자연어 검색 질문",
        min_length=2,
        max_length=500,
    )
