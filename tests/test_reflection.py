"""자기 검증 (Reflection) 기능 테스트."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import Settings
from app.models.domain import ChunkResult
from app.models.request import SearchRequest
from app.services.search_orchestrator import SearchOrchestrator, _mean_distance


def _make_chunks(distances: list[float], prefix: str = "page") -> list[ChunkResult]:
    """주어진 distance 값으로 ChunkResult 리스트를 생성한다."""
    return [
        ChunkResult(
            chunk_id=f"{prefix}_{i}",
            page_id=f"{prefix}-{i}",
            page_title=f"문서 {i}",
            breadcrumb=f"경로 > {i}",
            category="all",
            content=f"내용 {i}",
            source_url=f"https://notion.so/{prefix}-{i}",
            source_type="notion",
            distance=d,
        )
        for i, d in enumerate(distances)
    ]


def _make_settings(**overrides) -> MagicMock:
    """테스트용 Settings mock을 생성한다."""
    settings = MagicMock(spec=Settings)
    settings.reflection_enabled = overrides.get("reflection_enabled", True)
    settings.reflection_distance_threshold = overrides.get("reflection_distance_threshold", 0.65)
    settings.reflection_min_chunks = overrides.get("reflection_min_chunks", 2)
    return settings


def _make_orchestrator(
    chunks: list[ChunkResult],
    settings: MagicMock | None = None,
    reformulated_query: str = "재구성된 쿼리",
    reflection_chunks: list[ChunkResult] | None = None,
) -> SearchOrchestrator:
    """테스트용 SearchOrchestrator를 생성한다."""
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.1] * 768

    mock_vector_search = AsyncMock()
    if reflection_chunks is not None:
        mock_vector_search.search.side_effect = [chunks, reflection_chunks]
    else:
        mock_vector_search.search.return_value = chunks
    mock_vector_search.result_limit = 8

    mock_llm = AsyncMock()
    mock_llm.generate_answer.return_value = ("답변 [출처 1]", [1], [])
    mock_llm.reformulate_query.return_value = reformulated_query

    return SearchOrchestrator(
        embedder=mock_embedder,
        vector_search=mock_vector_search,
        llm=mock_llm,
        settings=settings,
    )


class TestMeanDistance:
    def test_normal(self):
        chunks = _make_chunks([0.1, 0.3, 0.5])
        assert abs(_mean_distance(chunks) - 0.3) < 1e-9

    def test_empty(self):
        assert _mean_distance([]) == 1.0


class TestAssessRelevance:
    def test_sufficient_relevance(self):
        settings = _make_settings()
        orch = _make_orchestrator(_make_chunks([0.3, 0.4]), settings=settings)
        assert orch._assess_relevance(_make_chunks([0.3, 0.4])) is True

    def test_high_distance_triggers(self):
        settings = _make_settings()
        orch = _make_orchestrator(_make_chunks([0.7, 0.8]), settings=settings)
        assert orch._assess_relevance(_make_chunks([0.7, 0.8])) is False

    def test_too_few_chunks_triggers(self):
        settings = _make_settings(reflection_min_chunks=2)
        orch = _make_orchestrator(_make_chunks([0.3]), settings=settings)
        assert orch._assess_relevance(_make_chunks([0.3])) is False

    def test_no_settings_returns_true(self):
        orch = _make_orchestrator(_make_chunks([0.9, 0.9]))
        assert orch._assess_relevance(_make_chunks([0.9, 0.9])) is True


class TestDeduplicateByPage:
    def test_removes_duplicates(self):
        chunks = [
            ChunkResult(
                chunk_id="c1",
                page_id="p1",
                page_title="A",
                breadcrumb="",
                category="all",
                content="1",
                source_url="",
                source_type="notion",
                distance=0.1,
            ),
            ChunkResult(
                chunk_id="c2",
                page_id="p1",
                page_title="A",
                breadcrumb="",
                category="all",
                content="2",
                source_url="",
                source_type="notion",
                distance=0.2,
            ),
            ChunkResult(
                chunk_id="c3",
                page_id="p2",
                page_title="B",
                breadcrumb="",
                category="all",
                content="3",
                source_url="",
                source_type="notion",
                distance=0.3,
            ),
        ]
        result = SearchOrchestrator._deduplicate_by_page(chunks)
        assert len(result) == 2
        assert result[0].chunk_id == "c1"
        assert result[1].chunk_id == "c3"


@pytest.mark.asyncio
async def test_reflection_not_triggered_on_good_results():
    """관련도가 충분하면 reflection이 발동하지 않아야 한다."""
    good_chunks = _make_chunks([0.2, 0.3, 0.4])
    settings = _make_settings()
    orch = _make_orchestrator(good_chunks, settings=settings)

    request = SearchRequest(category="all", query="테스트 쿼리")
    response = await orch.search(request)

    assert response.metadata.reflection_triggered is False
    orch._llm.reformulate_query.assert_not_called()


@pytest.mark.asyncio
async def test_reflection_triggered_on_high_distance():
    """평균 distance가 높으면 reflection이 발동해야 한다."""
    bad_chunks = _make_chunks([0.7, 0.8, 0.9])
    better_chunks = _make_chunks([0.3, 0.4], prefix="new")
    settings = _make_settings()
    orch = _make_orchestrator(
        bad_chunks,
        settings=settings,
        reformulated_query="개선된 쿼리",
        reflection_chunks=better_chunks,
    )

    request = SearchRequest(category="all", query="테스트 쿼리")
    response = await orch.search(request)

    assert response.metadata.reflection_triggered is True
    orch._llm.reformulate_query.assert_called_once()


@pytest.mark.asyncio
async def test_reflection_triggered_on_too_few_chunks():
    """청크 수가 부족하면 reflection이 발동해야 한다."""
    few_chunks = _make_chunks([0.3])
    better_chunks = _make_chunks([0.2, 0.25], prefix="new")
    settings = _make_settings(reflection_min_chunks=2)
    orch = _make_orchestrator(
        few_chunks,
        settings=settings,
        reformulated_query="개선된 쿼리",
        reflection_chunks=better_chunks,
    )

    request = SearchRequest(category="all", query="테스트 쿼리")
    response = await orch.search(request)

    assert response.metadata.reflection_triggered is True


@pytest.mark.asyncio
async def test_reflection_accepts_better_results():
    """reflection 결과가 더 나으면 채택해야 한다."""
    bad_chunks = _make_chunks([0.7, 0.8])
    better_chunks = _make_chunks([0.3, 0.4], prefix="new")
    settings = _make_settings()
    orch = _make_orchestrator(
        bad_chunks,
        settings=settings,
        reformulated_query="개선된 쿼리",
        reflection_chunks=better_chunks,
    )

    request = SearchRequest(category="all", query="테스트 쿼리")
    await orch.search(request)

    # LLM이 새 청크로 호출되었는지 확인 (better_chunks는 2개)
    call_args = orch._llm.generate_answer.call_args
    chunks_passed = call_args[0][2]  # 3번째 positional arg = chunks
    assert len(chunks_passed) == 2
    assert chunks_passed[0].page_id == "new-0"


@pytest.mark.asyncio
async def test_reflection_rejects_worse_results():
    """reflection 결과가 더 나쁘면 원본을 유지해야 한다."""
    original_chunks = _make_chunks([0.7, 0.8])
    worse_chunks = _make_chunks([0.85, 0.9], prefix="new")
    settings = _make_settings()
    orch = _make_orchestrator(
        original_chunks,
        settings=settings,
        reformulated_query="개선된 쿼리",
        reflection_chunks=worse_chunks,
    )

    request = SearchRequest(category="all", query="테스트 쿼리")
    await orch.search(request)

    call_args = orch._llm.generate_answer.call_args
    chunks_passed = call_args[0][2]
    assert chunks_passed[0].page_id == "page-0"  # 원본 유지


@pytest.mark.asyncio
async def test_reflection_disabled_via_config():
    """reflection_enabled=False이면 발동하지 않아야 한다."""
    bad_chunks = _make_chunks([0.7, 0.8])
    settings = _make_settings(reflection_enabled=False)
    orch = _make_orchestrator(bad_chunks, settings=settings)

    request = SearchRequest(category="all", query="테스트 쿼리")
    response = await orch.search(request)

    assert response.metadata.reflection_triggered is False
    orch._llm.reformulate_query.assert_not_called()


@pytest.mark.asyncio
async def test_reflection_same_query_skips_research():
    """재구성된 쿼리가 원본과 같으면 재검색을 건너뛰어야 한다."""
    bad_chunks = _make_chunks([0.7, 0.8])
    settings = _make_settings()
    orch = _make_orchestrator(
        bad_chunks,
        settings=settings,
        reformulated_query="테스트 쿼리",  # 원본과 동일
    )

    request = SearchRequest(category="all", query="테스트 쿼리")
    await orch.search(request)

    # vector_search.search는 1번만 호출 (재검색 없음)
    assert orch._vector_search.search.call_count == 1


@pytest.mark.asyncio
async def test_reflection_llm_error_graceful_fallback():
    """LLM reformulation이 실패하면 원본 쿼리로 fallback해야 한다."""
    bad_chunks = _make_chunks([0.7, 0.8])
    settings = _make_settings()
    orch = _make_orchestrator(bad_chunks, settings=settings)
    # reformulate_query가 원본 쿼리를 반환하도록 설정 (에러 시 동작)
    orch._llm.reformulate_query.return_value = "테스트 쿼리"

    request = SearchRequest(category="all", query="테스트 쿼리")
    await orch.search(request)

    # 재검색 없이 원본 결과 사용
    assert orch._vector_search.search.call_count == 1
