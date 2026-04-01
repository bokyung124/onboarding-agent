"""온보딩 전용 검색 엔드포인트 테스트."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.domain import ChunkResult
from app.models.request import OnboardingSearchRequest
from app.services.search_orchestrator import SearchOrchestrator


@pytest.mark.asyncio
async def test_orchestrator_passes_is_onboarding(mock_embedder: MagicMock):
    """온보딩 검색 시 vector_search에 is_onboarding=True가 전달되어야 한다."""
    mock_vector_search = AsyncMock()
    mock_vector_search.search.return_value = []
    mock_vector_search.result_limit = 10

    mock_llm = AsyncMock()
    mock_llm.generate_answer.return_value = (
        "관련 문서를 찾지 못했습니다. 다른 검색어로 시도해 주세요.",
        [],
        [],
    )

    orchestrator = SearchOrchestrator(
        embedder=mock_embedder,
        vector_search=mock_vector_search,
        llm=mock_llm,
    )

    request = OnboardingSearchRequest(category="seo", query="SEO 온보딩 절차")
    await orchestrator.search(request, is_onboarding=True)

    mock_vector_search.search.assert_called_once()
    call_kwargs = mock_vector_search.search.call_args
    assert call_kwargs.kwargs["is_onboarding"] is True


@pytest.mark.asyncio
async def test_orchestrator_onboarding_with_results(
    mock_embedder: MagicMock,
):
    """온보딩 검색 결과가 있으면 답변과 출처를 반환해야 한다."""
    onboarding_chunks = [
        ChunkResult(
            chunk_id="seo_page_0",
            page_id="seo-onboarding",
            page_title="SEO 온보딩 매뉴얼",
            breadcrumb="SEO > 온보딩 매뉴얼",
            category="seo",
            content="SEO 팀 온보딩 첫 번째 단계입니다.",
            source_url="https://notion.so/seo-onboarding",
            source_type="notion",
            distance=0.1,
        ),
    ]

    mock_vector_search = AsyncMock()
    mock_vector_search.search.return_value = onboarding_chunks
    mock_vector_search.result_limit = 10

    mock_llm = AsyncMock()
    mock_llm.generate_answer.return_value = (
        "SEO 온보딩 절차 [출처 1]",
        [1],
        ["SEO 키워드 리서치 방법은?", "GA4 설정은 어떻게 하나요?"],
    )

    orchestrator = SearchOrchestrator(
        embedder=mock_embedder,
        vector_search=mock_vector_search,
        llm=mock_llm,
    )

    request = OnboardingSearchRequest(category="seo", query="SEO 온보딩")
    response = await orchestrator.search(request, is_onboarding=True)

    assert "SEO" in response.answer
    assert len(response.sources) == 1
    assert response.sources[0].title == "SEO 온보딩 매뉴얼"
    assert response.category == "seo"


def test_onboarding_category_list():
    """온보딩 카테고리 목록이 8개여야 한다."""
    from app.models.categories import ONBOARDING_CATEGORY_DEFS

    assert len(ONBOARDING_CATEGORY_DEFS) == 8
    slugs = [slug for slug, *_ in ONBOARDING_CATEGORY_DEFS]
    assert "all" in slugs
    assert "seo" in slugs
    assert "crm" in slugs
    assert "tech" in slugs
    # 기존 카테고리(marketing, tools)는 온보딩에 없어야 한다
    assert "marketing" not in slugs
    assert "tools" not in slugs
