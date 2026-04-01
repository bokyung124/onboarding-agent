"""온보딩 전용 검색, 카테고리, 체크리스트 엔드포인트."""

import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.models.categories import ONBOARDING_CATEGORY_DEFS, OnboardingCategorySlug
from app.models.request import OnboardingSearchRequest
from app.models.response import (
    Category,
    CategoryListResponse,
    ChecklistResponse,
    SearchResponse,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

ONBOARDING_CATEGORIES = [
    Category(slug=slug, name=label) for slug, _, label, _ in ONBOARDING_CATEGORY_DEFS
]


@router.get("/categories", response_model=CategoryListResponse)
async def list_onboarding_categories() -> CategoryListResponse:
    """온보딩 전용 카테고리 목록을 반환한다."""
    return CategoryListResponse(categories=ONBOARDING_CATEGORIES)


@router.post("/search", response_model=SearchResponse)
async def onboarding_search(request: Request, body: OnboardingSearchRequest) -> SearchResponse:
    """온보딩 문서에서 질문을 검색하고 RAG 기반 답변을 반환한다."""
    orchestrator = request.app.state.orchestrator
    timeout: float = request.app.state.settings.search_timeout_seconds
    try:
        return await asyncio.wait_for(
            orchestrator.search(body, is_onboarding=True), timeout=timeout
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="검색 요청이 시간 초과되었습니다.")


@router.get("/{category}/checklist", response_model=ChecklistResponse)
async def get_onboarding_checklist(
    request: Request,
    category: OnboardingCategorySlug,
) -> ChecklistResponse:
    """카테고리별 온보딩 체크리스트(학습 경로)를 반환한다."""
    if category == "all":
        raise HTTPException(
            status_code=400,
            detail="체크리스트는 특정 카테고리를 선택해야 합니다. 'all'은 지원하지 않습니다.",
        )
    orchestrator = request.app.state.orchestrator
    timeout: float = request.app.state.settings.search_timeout_seconds
    try:
        return await asyncio.wait_for(orchestrator.generate_checklist(category), timeout=timeout)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="체크리스트 생성 요청이 시간 초과되었습니다.")
