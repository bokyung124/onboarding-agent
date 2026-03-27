"""검색 오케스트레이터 및 라우터 테스트."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.domain import ChunkResult
from app.models.request import SearchRequest
from app.services.search_orchestrator import SearchOrchestrator


@pytest.mark.asyncio
async def test_orchestrator_returns_answer_with_sources(
    sample_chunks: list[ChunkResult], mock_embedder: MagicMock
):
    """오케스트레이터가 답변과 출처를 포함한 응답을 반환해야 한다."""
    mock_vector_search = AsyncMock()
    mock_vector_search.search.return_value = sample_chunks

    mock_llm = AsyncMock()
    mock_llm.generate_answer.return_value = "Jira 프로젝트를 먼저 생성합니다 [출처 1]"

    orchestrator = SearchOrchestrator(
        embedder=mock_embedder,
        vector_search=mock_vector_search,
        llm=mock_llm,
    )

    request = SearchRequest(category="tech", query="프로젝트 세팅 방법")
    response = await orchestrator.search(request)

    assert response.answer
    assert len(response.sources) == 2
    assert response.sources[0].title == "SI 프로젝트 세팅 가이드"
    assert response.category == "tech"
    assert response.metadata.chunks_retrieved == 2
    assert response.metadata.latency_ms >= 0


@pytest.mark.asyncio
async def test_orchestrator_deduplicates_sources(mock_embedder: MagicMock):
    """같은 페이지에서 온 여러 청크의 출처를 중복 제거해야 한다."""
    duplicate_chunks = [
        ChunkResult(
            chunk_id="page1_0",
            page_id="page-1",
            page_title="가이드",
            breadcrumb="A > B",
            category="tech",
            content="내용 1",
            source_url="https://notion.so/page-1",
            source_type="notion",
            distance=0.1,
        ),
        ChunkResult(
            chunk_id="page1_1",
            page_id="page-1",
            page_title="가이드",
            breadcrumb="A > B",
            category="tech",
            content="내용 2",
            source_url="https://notion.so/page-1",
            source_type="notion",
            distance=0.2,
        ),
    ]

    mock_vector_search = AsyncMock()
    mock_vector_search.search.return_value = duplicate_chunks

    mock_llm = AsyncMock()
    mock_llm.generate_answer.return_value = "답변"

    orchestrator = SearchOrchestrator(
        embedder=mock_embedder,
        vector_search=mock_vector_search,
        llm=mock_llm,
    )

    request = SearchRequest(category="tech", query="테스트")
    response = await orchestrator.search(request)

    assert len(response.sources) == 1  # 중복 제거


@pytest.mark.asyncio
async def test_orchestrator_mixed_notion_slack_sources(mock_embedder: MagicMock):
    """Notion과 Slack 혼합 결과에서 source_type이 올바르게 설정되어야 한다."""
    mixed_chunks = [
        ChunkResult(
            chunk_id="page1_0",
            page_id="page-1",
            page_title="가이드",
            breadcrumb="A > B",
            category="tech",
            content="Notion 내용",
            source_url="https://notion.so/page-1",
            source_type="notion",
            distance=0.1,
        ),
        ChunkResult(
            chunk_id="slack_C123_1632997193.001200",
            page_id="slack_C123_1632997193.001200",
            page_title="#dev",
            breadcrumb="Slack > #dev",
            category="tech",
            content="Slack 대화 내용",
            source_url="https://workspace.slack.com/archives/C123/p1632997193001200",
            source_type="slack",
            distance=0.15,
        ),
    ]

    mock_vector_search = AsyncMock()
    mock_vector_search.search.return_value = mixed_chunks

    mock_llm = AsyncMock()
    mock_llm.generate_answer.return_value = "답변 [출처 1] [출처 2]"

    orchestrator = SearchOrchestrator(
        embedder=mock_embedder,
        vector_search=mock_vector_search,
        llm=mock_llm,
    )

    request = SearchRequest(category="tech", query="테스트")
    response = await orchestrator.search(request)

    assert len(response.sources) == 2
    assert response.sources[0].source_type == "notion"
    assert response.sources[1].source_type == "slack"


@pytest.mark.asyncio
async def test_orchestrator_empty_chunks(mock_embedder: MagicMock):
    """검색 결과가 없으면 기본 메시지를 반환해야 한다."""
    mock_vector_search = AsyncMock()
    mock_vector_search.search.return_value = []

    mock_llm = AsyncMock()
    mock_llm.generate_answer.return_value = (
        "관련 문서를 찾지 못했습니다. 다른 검색어로 시도해 주세요."
    )

    orchestrator = SearchOrchestrator(
        embedder=mock_embedder,
        vector_search=mock_vector_search,
        llm=mock_llm,
    )

    request = SearchRequest(category="all", query="없는 내용")
    response = await orchestrator.search(request)

    assert "찾지 못했습니다" in response.answer
    assert len(response.sources) == 0
