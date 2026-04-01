"""멀티스텝 에이전트 테스트."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.domain import ChunkResult
from app.services.search_orchestrator import SearchOrchestrator


def _make_chunk(chunk_id: str, page_id: str, content: str = "text") -> ChunkResult:
    return ChunkResult(
        chunk_id=chunk_id,
        page_id=page_id,
        page_title=f"Page {page_id}",
        breadcrumb="test",
        category="all",
        content=content,
        source_url="https://example.com",
        source_type="notion",
        distance=0.3,
    )


@pytest.fixture
def mock_services():
    embedder = MagicMock()
    embedder.embed_query.return_value = [0.1] * 768
    vector_search = AsyncMock()
    vector_search.result_limit = 8
    vector_search._settings = MagicMock()
    llm = AsyncMock()
    return embedder, vector_search, llm


async def test_multi_step_single_query(mock_services) -> None:
    """단순 질문은 분해 없이 일반 search로 폴백."""
    embedder, vector_search, llm = mock_services
    llm.decompose_query.return_value = ["단순 질문"]
    vector_search.search.return_value = [_make_chunk("c1", "p1")]
    llm.generate_answer.return_value = ("답변", [1], ["후속"])

    from app.models.request import SearchRequest

    orch = SearchOrchestrator(embedder, vector_search, llm)
    request = SearchRequest(category="all", query="단순 질문")
    await orch.multi_step_search(request)

    # 단순 질문이면 search()로 폴백 (decompose가 1개만 반환)
    # search() 내부에서 embedder, vector_search, llm 호출
    llm.decompose_query.assert_called_once_with("단순 질문")


async def test_multi_step_combines_chunks(mock_services) -> None:
    """복합 질문은 하위 쿼리별 검색 후 청크를 합산."""
    embedder, vector_search, llm = mock_services
    llm.decompose_query.return_value = ["SEO 기초", "키워드 리서치"]
    vector_search.search.side_effect = [
        [_make_chunk("c1", "p1", "SEO 기초 내용")],
        [_make_chunk("c2", "p2", "키워드 리서치 내용")],
    ]
    llm.generate_answer.return_value = ("종합 답변", [1, 2], [])

    from app.models.request import SearchRequest

    orch = SearchOrchestrator(embedder, vector_search, llm)
    request = SearchRequest(category="all", query="SEO에서 키워드 리서치까지 전체 프로세스")
    response = await orch.multi_step_search(request)

    assert response.answer == "종합 답변"
    assert vector_search.search.call_count == 2
    # LLM은 합산된 청크로 한 번 호출
    llm.generate_answer.assert_called_once()
    call_args = llm.generate_answer.call_args
    chunks_passed = call_args[0][2]
    assert len(chunks_passed) == 2


async def test_multi_step_deduplicates_chunks(mock_services) -> None:
    """하위 쿼리에서 중복 청크는 제거."""
    embedder, vector_search, llm = mock_services
    llm.decompose_query.return_value = ["q1", "q2"]
    # 동일 chunk_id가 두 검색에서 반환
    vector_search.search.side_effect = [
        [_make_chunk("c1", "p1"), _make_chunk("c2", "p2")],
        [_make_chunk("c1", "p1"), _make_chunk("c3", "p3")],
    ]
    llm.generate_answer.return_value = ("답변", [], [])

    from app.models.request import SearchRequest

    orch = SearchOrchestrator(embedder, vector_search, llm)
    request = SearchRequest(category="all", query="복잡한 질문")
    await orch.multi_step_search(request)

    chunks_passed = llm.generate_answer.call_args[0][2]
    # c1이 중복 → 3개만 전달 (chunk_id 중복 제거 + page_id 중복 제거)
    assert len(chunks_passed) == 3
