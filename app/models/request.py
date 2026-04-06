from pydantic import BaseModel, Field

from app.models.categories import CategorySlug, OnboardingCategorySlug


class SearchRequest(BaseModel):
    category: CategorySlug = Field(
        default="all",
        description="검색 카테고리",
    )
    query: str = Field(
        description="자연어 검색 질문",
        min_length=2,
        max_length=500,
    )
    user_id: str | None = Field(default=None, description="사용자 ID (Slack user ID 등)")
    client_name: str | None = Field(default=None, description="고객사 이름 필터")
    tags: str | None = Field(default=None, description="태그 필터 (부분 일치)")


class OnboardingSearchRequest(BaseModel):
    category: OnboardingCategorySlug = Field(
        default="all",
        description="온보딩 검색 카테고리",
    )
    query: str = Field(
        description="자연어 검색 질문",
        min_length=2,
        max_length=500,
    )
    user_id: str | None = Field(default=None, description="사용자 ID (Slack user ID 등)")
    client_name: str | None = Field(default=None, description="고객사 이름 필터")
    tags: str | None = Field(default=None, description="태그 필터 (부분 일치)")
