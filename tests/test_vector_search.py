"""벡터 검색 서비스 테스트."""

import asyncio
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.services.vector_search import VectorSearchService


@pytest.fixture
def settings() -> Settings:
    return Settings(
        gcp_project_id="test-project",
        gemini_api_key="test-key",
        bq_dataset="test_dataset",
    )


@pytest.fixture
def service(mock_bq_client: MagicMock, settings: Settings) -> VectorSearchService:
    return VectorSearchService(mock_bq_client, settings)


def test_default_settings(service: VectorSearchService):
    """기본 설정값을 확인한다."""
    assert service._settings.bq_vectors_table == "mart_enterprise_vectors"
    assert service._settings.search_top_k == 50
    assert service._settings.search_fraction_lists == 0.3


def test_postfilter_with_category(service: VectorSearchService, mock_bq_client: MagicMock):
    """카테고리 필터 시 TABLE 참조(인덱스 활용) + post-filter를 사용한다."""
    mock_bq_client.query.return_value.result.return_value = []

    asyncio.get_event_loop().run_until_complete(
        service.search(query_embedding=[0.1] * 768, category="tech")
    )

    call_args = mock_bq_client.query.call_args
    query = call_args[0][0]

    assert "TABLE `" in query
    assert "base.category = @category" in query
    assert "distance <= @distance_threshold" in query


def test_no_category_filter_when_all(service: VectorSearchService, mock_bq_client: MagicMock):
    """전체 검색(all) 시 카테고리 필터 없이 TABLE 직접 참조한다."""
    mock_bq_client.query.return_value.result.return_value = []

    asyncio.get_event_loop().run_until_complete(
        service.search(query_embedding=[0.1] * 768, category="all")
    )

    call_args = mock_bq_client.query.call_args
    query = call_args[0][0]

    assert "TABLE `" in query
    assert "base.category = @category" not in query


def test_fraction_lists_option_in_query(service: VectorSearchService, mock_bq_client: MagicMock):
    """VECTOR_SEARCH에 fraction_lists_to_search 옵션이 포함된다."""
    mock_bq_client.query.return_value.result.return_value = []

    asyncio.get_event_loop().run_until_complete(service.search(query_embedding=[0.1] * 768))

    call_args = mock_bq_client.query.call_args
    query = call_args[0][0]

    assert "fraction_lists_to_search" in query
    assert "0.3" in query


def test_postfilter_with_multiple_filters(service: VectorSearchService, mock_bq_client: MagicMock):
    """복수 필터(category + client_name + tags) 시 모두 post-filter에 포함된다."""
    mock_bq_client.query.return_value.result.return_value = []

    asyncio.get_event_loop().run_until_complete(
        service.search(
            query_embedding=[0.1] * 768,
            category="marketing",
            client_name="acme",
            tags="onboarding",
        )
    )

    call_args = mock_bq_client.query.call_args
    query = call_args[0][0]

    assert "TABLE `" in query
    assert "base.category = @category" in query
    assert "base.client_name = @client_name" in query
    assert "base.tags LIKE @tags_pattern" in query


def test_postfilter_with_is_onboarding(service: VectorSearchService, mock_bq_client: MagicMock):
    """is_onboarding=True 시 post-filter에 is_onboarding 조건이 포함된다."""
    mock_bq_client.query.return_value.result.return_value = []

    asyncio.get_event_loop().run_until_complete(
        service.search(
            query_embedding=[0.1] * 768,
            category="seo",
            is_onboarding=True,
        )
    )

    call_args = mock_bq_client.query.call_args
    query = call_args[0][0]

    assert "base.is_onboarding = TRUE" in query
    assert "base.category = @category" in query


def test_no_onboarding_filter_by_default(service: VectorSearchService, mock_bq_client: MagicMock):
    """is_onboarding 미지정 시 onboarding 필터가 없어야 한다."""
    mock_bq_client.query.return_value.result.return_value = []

    asyncio.get_event_loop().run_until_complete(
        service.search(query_embedding=[0.1] * 768, category="tech")
    )

    call_args = mock_bq_client.query.call_args
    query = call_args[0][0]

    assert "is_onboarding" not in query


def test_no_join_in_query(service: VectorSearchService, mock_bq_client: MagicMock):
    """벡터 검색 쿼리에 불필요한 JOIN이 없어야 한다."""
    mock_bq_client.query.return_value.result.return_value = []

    asyncio.get_event_loop().run_until_complete(service.search(query_embedding=[0.1] * 768))

    call_args = mock_bq_client.query.call_args
    query = call_args[0][0]

    assert "LEFT JOIN" not in query
    assert "VECTOR_SEARCH" in query
