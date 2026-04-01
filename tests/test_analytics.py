"""검색 분석 서비스 테스트."""

from unittest.mock import MagicMock

import pytest

from app.services.analytics import SearchAnalytics


@pytest.fixture
def analytics() -> SearchAnalytics:
    bq_client = MagicMock()
    bq_client.insert_rows_json.return_value = []
    return SearchAnalytics(
        bq_client=bq_client,
        project_id="test-project",
        dataset="test_dataset",
        buffer_size=3,
    )


async def test_analytics_log_search_buffers(analytics: SearchAnalytics) -> None:
    """로그가 버퍼 크기 미만이면 flush하지 않는다."""
    await analytics.log_search(
        query="test query",
        category="all",
        chunks_retrieved=5,
        sources_count=3,
        latency_ms=200,
    )
    assert len(analytics._buffer) == 1
    analytics._client.insert_rows_json.assert_not_called()


async def test_analytics_auto_flush_on_buffer_full(analytics: SearchAnalytics) -> None:
    """버퍼가 가득 차면 자동 flush한다."""
    for i in range(3):
        await analytics.log_search(
            query=f"query {i}",
            category="all",
            chunks_retrieved=1,
            sources_count=1,
            latency_ms=100,
        )
    # buffer_size=3이므로 3번째에 자동 flush
    analytics._client.insert_rows_json.assert_called_once()
    assert len(analytics._buffer) == 0


async def test_analytics_manual_flush(analytics: SearchAnalytics) -> None:
    """수동 flush가 올바르게 동작한다."""
    await analytics.log_search(
        query="test",
        category="tech",
        chunks_retrieved=2,
        sources_count=1,
        latency_ms=150,
    )
    count = await analytics.flush()
    assert count == 1
    analytics._client.insert_rows_json.assert_called_once()
    rows = analytics._client.insert_rows_json.call_args[0][1]
    assert rows[0]["query"] == "test"
    assert rows[0]["category"] == "tech"


async def test_analytics_flush_empty(analytics: SearchAnalytics) -> None:
    """빈 버퍼 flush는 0을 반환한다."""
    count = await analytics.flush()
    assert count == 0
    analytics._client.insert_rows_json.assert_not_called()


async def test_analytics_log_with_optional_fields(analytics: SearchAnalytics) -> None:
    """선택 필드가 올바르게 기록된다."""
    await analytics.log_search(
        query="고객사 검색",
        category="marketing",
        chunks_retrieved=3,
        sources_count=2,
        latency_ms=300,
        is_onboarding=True,
        user_id="U123",
        success=False,
        client_name="고객사A",
        tags="SEO,CRM",
    )
    row = analytics._buffer[0]
    assert row["user_id"] == "U123"
    assert row["is_onboarding"] is True
    assert row["success"] is False
    assert row["client_name"] == "고객사A"
    assert row["tags"] == "SEO,CRM"
