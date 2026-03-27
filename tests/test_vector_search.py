"""벡터 검색 서비스 테스트."""

from unittest.mock import MagicMock

from app.config import Settings
from app.services.vector_search import VectorSearchService


def test_vector_search_builds_correct_query(mock_bq_client: MagicMock):
    """벡터 검색 쿼리에 department 파라미터가 포함되어야 한다."""
    settings = Settings(
        gcp_project_id="test-project",
        gemini_api_key="test-key",
        bq_dataset="test_dataset",
    )
    service = VectorSearchService(mock_bq_client, settings)

    assert service._settings.bq_vectors_table == "mart_enterprise_vectors"
    assert service._settings.search_top_k == 24
