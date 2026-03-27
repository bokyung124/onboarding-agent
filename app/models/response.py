from pydantic import BaseModel, Field


class Source(BaseModel):
    title: str = Field(description="페이지 제목 또는 채널명")
    url: str = Field(description="원본 URL (Notion 또는 Slack)")
    breadcrumb: str = Field(description="경로")
    page_id: str | None = Field(default=None)
    source_type: str = Field(default="notion", description="notion 또는 slack")


class SearchMetadata(BaseModel):
    chunks_retrieved: int
    latency_ms: int


class SearchResponse(BaseModel):
    answer: str = Field(description="인용이 포함된 생성 답변")
    sources: list[Source]
    category: str
    metadata: SearchMetadata


class Category(BaseModel):
    slug: str
    name: str


class CategoryListResponse(BaseModel):
    categories: list[Category]


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
