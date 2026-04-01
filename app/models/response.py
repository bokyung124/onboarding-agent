from pydantic import BaseModel, Field


class Source(BaseModel):
    title: str = Field(description="페이지 제목 또는 채널명")
    url: str = Field(description="원본 URL (Notion 또는 Slack)")
    breadcrumb: str = Field(description="경로")
    page_id: str | None = Field(default=None)
    source_type: str = Field(default="notion", description="notion 또는 slack")
    client_name: str | None = Field(default=None, description="고객사 이름")
    tags: str | None = Field(default=None, description="태그")


class SearchMetadata(BaseModel):
    chunks_retrieved: int
    latency_ms: int


class SearchResponse(BaseModel):
    answer: str = Field(description="인용이 포함된 생성 답변")
    sources: list[Source]
    category: str
    metadata: SearchMetadata
    follow_up_questions: list[str] = Field(default_factory=list, description="후속 질문 추천 목록")


class Category(BaseModel):
    slug: str
    name: str


class CategoryListResponse(BaseModel):
    categories: list[Category]


class ChecklistStep(BaseModel):
    step_number: int = Field(description="1-based 단계 번호")
    title: str = Field(description="단계 제목 (예: GA4 기초 이해하기)")
    description: str = Field(description="2~3문장 설명, Slack mrkdwn 형식")
    search_query: str = Field(description="상세 검색용 쿼리")


class ChecklistResponse(BaseModel):
    category: str
    category_name: str
    title: str = Field(description="체크리스트 제목 (예: SEO 팀 온보딩 7단계)")
    steps: list[ChecklistStep]
    sources: list[Source]
    metadata: SearchMetadata


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
