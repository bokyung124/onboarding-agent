"""온보딩 체크리스트/학습 경로 기능 테스트."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.cache import ChecklistCache
from app.models.domain import ChunkResult
from app.models.response import (
    ChecklistResponse,
    ChecklistStep,
    SearchMetadata,
    Source,
)
from app.services.search_orchestrator import SearchOrchestrator
from app.services.slack_formatter import format_checklist_blocks


def test_checklist_response_model():
    """ChecklistStep, ChecklistResponse 모델 생성을 검증한다."""
    step = ChecklistStep(
        step_number=1,
        title="GA4 기초 이해하기",
        description="GA4의 기본 구조와 이벤트 모델을 학습합니다.",
        search_query="GA4 기본 구조와 이벤트 모델",
    )
    assert step.step_number == 1
    assert step.title == "GA4 기초 이해하기"

    response = ChecklistResponse(
        category="seo",
        category_name="SEO",
        title="SEO 팀 온보딩 3단계",
        steps=[step],
        sources=[
            Source(
                title="SEO 가이드",
                url="https://notion.so/seo",
                breadcrumb="SEO > 가이드",
            )
        ],
        metadata=SearchMetadata(chunks_retrieved=5, latency_ms=1200),
    )
    assert len(response.steps) == 1
    assert response.category == "seo"


@pytest.mark.asyncio
async def test_generate_checklist_orchestrator(
    mock_embedder: MagicMock,
    sample_onboarding_chunks: list[ChunkResult],
):
    """오케스트레이터가 체크리스트 생성 시 올바르게 호출하는지 검증한다."""
    mock_vector_search = AsyncMock()
    mock_vector_search.search.return_value = sample_onboarding_chunks

    mock_llm = AsyncMock()
    mock_llm.generate_checklist.return_value = (
        "SEO 팀 온보딩 3단계",
        [
            {
                "step_number": 1,
                "title": "SEO 기초 학습",
                "description": "검색엔진 기본 원리를 이해합니다.",
                "search_query": "SEO 기초 개념",
            },
            {
                "step_number": 2,
                "title": "도구 설정",
                "description": "GSC와 GA4를 설정합니다.",
                "search_query": "SEO 도구 설정 방법",
            },
            {
                "step_number": 3,
                "title": "업무 프로세스 파악",
                "description": "전체 SEO 워크플로우를 익힙니다.",
                "search_query": "SEO 업무 프로세스",
            },
        ],
    )

    orchestrator = SearchOrchestrator(
        embedder=mock_embedder,
        vector_search=mock_vector_search,
        llm=mock_llm,
    )

    response = await orchestrator.generate_checklist("seo")

    assert response.category == "seo"
    assert response.title == "SEO 팀 온보딩 3단계"
    assert len(response.steps) == 3
    assert response.steps[0].title == "SEO 기초 학습"
    assert len(response.sources) == 3

    mock_vector_search.search.assert_called_once()
    call_kwargs = mock_vector_search.search.call_args
    assert call_kwargs.kwargs["is_onboarding"] is True
    mock_llm.generate_checklist.assert_called_once_with("seo", sample_onboarding_chunks)


@pytest.mark.asyncio
async def test_generate_checklist_cache_hit(mock_embedder: MagicMock):
    """캐시 HIT 시 embedder/vector_search/llm이 호출되지 않아야 한다."""
    cached_response = ChecklistResponse(
        category="seo",
        category_name="SEO",
        title="SEO 팀 온보딩 3단계",
        steps=[
            ChecklistStep(
                step_number=1,
                title="기초",
                description="기초 학습",
                search_query="SEO 기초",
            ),
        ],
        sources=[],
        metadata=SearchMetadata(chunks_retrieved=3, latency_ms=500),
    )

    checklist_cache = ChecklistCache(maxsize=20, ttl=3600)
    checklist_cache.set("seo", cached_response)

    mock_vector_search = AsyncMock()
    mock_llm = AsyncMock()

    orchestrator = SearchOrchestrator(
        embedder=mock_embedder,
        vector_search=mock_vector_search,
        llm=mock_llm,
        checklist_cache=checklist_cache,
    )

    response = await orchestrator.generate_checklist("seo")

    assert response.title == "SEO 팀 온보딩 3단계"
    mock_embedder.embed_query.assert_not_called()
    mock_vector_search.search.assert_not_called()
    mock_llm.generate_checklist.assert_not_called()


@pytest.mark.asyncio
async def test_generate_checklist_empty_chunks(mock_embedder: MagicMock):
    """검색 결과가 없을 때 빈 steps를 반환해야 한다."""
    mock_vector_search = AsyncMock()
    mock_vector_search.search.return_value = []

    mock_llm = AsyncMock()
    mock_llm.generate_checklist.return_value = ("SEO 온보딩 체크리스트", [])

    orchestrator = SearchOrchestrator(
        embedder=mock_embedder,
        vector_search=mock_vector_search,
        llm=mock_llm,
    )

    response = await orchestrator.generate_checklist("seo")

    assert response.steps == []
    assert response.category == "seo"


def test_format_checklist_blocks():
    """체크리스트 Slack 블록 구조를 검증한다."""
    response = ChecklistResponse(
        category="seo",
        category_name="SEO",
        title="SEO 팀 온보딩 2단계",
        steps=[
            ChecklistStep(
                step_number=1,
                title="기초 학습",
                description="SEO 기본 개념을 익힙니다.",
                search_query="SEO 기초 개념",
            ),
            ChecklistStep(
                step_number=2,
                title="도구 설정",
                description="GA4와 GSC를 설정합니다.",
                search_query="GA4 GSC 설정",
            ),
        ],
        sources=[
            Source(
                title="SEO 가이드",
                url="https://notion.so/seo",
                breadcrumb="SEO > 가이드",
                source_type="notion",
            ),
        ],
        metadata=SearchMetadata(chunks_retrieved=3, latency_ms=800),
    )

    blocks = format_checklist_blocks(response)

    # 헤더 블록
    assert blocks[0]["type"] == "header"
    assert "SEO 팀 온보딩 2단계" in blocks[0]["text"]["text"]

    # 단계 블록 (section with accessory button)
    step_blocks = [b for b in blocks if b["type"] == "section" and "accessory" in b]
    assert len(step_blocks) == 2
    assert "기초 학습" in step_blocks[0]["text"]["text"]
    assert step_blocks[0]["accessory"]["type"] == "button"
    assert step_blocks[0]["accessory"]["action_id"] == "checklist_step_1"

    # 출처 context 블록
    context_blocks = [b for b in blocks if b["type"] == "context"]
    assert any("참고 문서" in str(b) for b in context_blocks)

    # 메타데이터 context 블록
    assert any("응답 시간" in str(b) for b in context_blocks)
