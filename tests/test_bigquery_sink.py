"""BigQueryBatchSink 및 crawl_all() 배치 flush 테스트."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.extract.bigquery_sink import BigQueryBatchSink

# --- BigQueryBatchSink ---


@pytest.fixture
def mock_bq_sink() -> BigQueryBatchSink:
    with patch("pipeline.extract.bigquery_sink.bigquery") as mock_bq:
        mock_bq.WriteDisposition.WRITE_TRUNCATE = "WRITE_TRUNCATE"
        mock_bq.WriteDisposition.WRITE_APPEND = "WRITE_APPEND"
        mock_bq.SourceFormat.NEWLINE_DELIMITED_JSON = "NEWLINE_DELIMITED_JSON"
        mock_bq.LoadJobConfig.return_value = MagicMock()

        sink = BigQueryBatchSink(
            project_id="test-project",
            dataset="test_dataset",
            write_disposition="WRITE_TRUNCATE",
        )
        # mock _load to avoid real BigQuery calls
        sink._load = MagicMock()
        return sink


async def test_flush_calls_load(mock_bq_sink: BigQueryBatchSink) -> None:
    pages = [{"page_id": "p1", "properties_json": {"key": "val"}, "_extracted_at": "t"}]
    blocks = [{"block_id": "b1", "_extracted_at": "t"}]

    await mock_bq_sink.flush(pages, blocks, [], [])

    assert mock_bq_sink._load.call_count == 2  # pages + blocks
    assert mock_bq_sink.total_pages == 1
    assert mock_bq_sink.total_blocks == 1


async def test_flush_skips_empty_data(mock_bq_sink: BigQueryBatchSink) -> None:
    await mock_bq_sink.flush([], [], [], [])
    mock_bq_sink._load.assert_not_called()


async def test_flush_serializes_json_fields(mock_bq_sink: BigQueryBatchSink) -> None:
    pages = [{"page_id": "p1", "properties_json": {"name": "test"}, "_extracted_at": "t"}]
    databases = [{"database_id": "d1", "schema_json": {"col": "text"}, "_extracted_at": "t"}]

    await mock_bq_sink.flush(pages, [], databases, [])

    # properties_json and schema_json should be serialized to strings
    assert isinstance(pages[0]["properties_json"], str)
    assert isinstance(databases[0]["schema_json"], str)


async def test_truncate_then_append_per_table(mock_bq_sink: BigQueryBatchSink) -> None:
    """각 테이블별로 첫 load는 WRITE_TRUNCATE, 이후는 WRITE_APPEND."""
    # 첫 flush: pages만 있음
    await mock_bq_sink.flush([{"page_id": "p1", "_extracted_at": "t"}], [], [], [])
    first_config = mock_bq_sink._load.call_args_list[0][0][2]
    assert first_config.write_disposition == "WRITE_TRUNCATE"

    mock_bq_sink._load.reset_mock()

    # 두 번째 flush: pages(APPEND) + blocks(첫 등장이므로 TRUNCATE)
    await mock_bq_sink.flush(
        [{"page_id": "p2", "_extracted_at": "t"}],
        [{"block_id": "b1", "_extracted_at": "t"}],
        [],
        [],
    )
    # pages → APPEND (두 번째), blocks → TRUNCATE (첫 번째)
    pages_config = mock_bq_sink._load.call_args_list[0][0][2]
    blocks_config = mock_bq_sink._load.call_args_list[1][0][2]
    assert pages_config.write_disposition == "WRITE_APPEND"
    assert blocks_config.write_disposition == "WRITE_TRUNCATE"


async def test_total_counters(mock_bq_sink: BigQueryBatchSink) -> None:
    await mock_bq_sink.flush(
        [{"page_id": "p1", "_extracted_at": "t"}],
        [{"block_id": "b1", "_extracted_at": "t"}, {"block_id": "b2", "_extracted_at": "t"}],
        [],
        [{"comment_id": "c1", "_extracted_at": "t"}],
    )
    await mock_bq_sink.flush(
        [{"page_id": "p2", "_extracted_at": "t"}],
        [],
        [{"database_id": "d1", "_extracted_at": "t"}],
        [],
    )

    assert mock_bq_sink.total_pages == 2
    assert mock_bq_sink.total_blocks == 2
    assert mock_bq_sink.total_databases == 1
    assert mock_bq_sink.total_comments == 1


# --- crawl_all() with sink ---


async def test_crawl_all_without_sink_returns_data() -> None:
    """sink=None이면 기존처럼 데이터를 튜플로 반환한다."""
    from pipeline.extract.notion_extractor import NotionExtractor

    with patch.object(NotionExtractor, "_get_seed_pages", return_value=[]):
        extractor = NotionExtractor(api_key="test-key")
        pages, blocks, databases, comments = await extractor.crawl_all()

    assert pages == []
    assert blocks == []
    assert databases == []
    assert comments == []


async def test_crawl_all_with_sink_flushes_batches() -> None:
    """sink가 있으면 batch_size마다 flush하고 빈 리스트를 반환한다."""
    from pipeline.extract.notion_extractor import NotionExtractor

    mock_sink = AsyncMock()
    seed_ids = [f"page-{i}" for i in range(5)]

    # 각 페이지 retrieve 결과
    mock_page = {
        "id": "page-0",
        "parent": {"type": "workspace"},
        "properties": {},
        "url": "https://notion.so/page-0",
        "created_time": "2026-01-01T00:00:00Z",
        "last_edited_time": "2026-01-01T00:00:00Z",
        "archived": False,
    }

    with (
        patch.object(NotionExtractor, "_get_seed_pages", return_value=seed_ids),
        patch("pipeline.extract.notion_extractor.rate_limited_call") as mock_call,
        patch.object(NotionExtractor, "_extract_page_blocks", return_value=[]),
        patch.object(NotionExtractor, "_extract_page_comments", return_value=[]),
    ):
        # rate_limited_call returns page data for pages.retrieve
        mock_call.return_value = {**mock_page}

        # Make each call return a different page_id
        async def side_effect(fn, **kwargs):
            page_id = kwargs.get("page_id", "unknown")
            return {**mock_page, "id": page_id}

        mock_call.side_effect = side_effect

        extractor = NotionExtractor(api_key="test-key")
        pages, blocks, databases, comments = await extractor.crawl_all(sink=mock_sink, batch_size=3)

    # sink should have been called (batch of 3, then remaining 2)
    assert mock_sink.flush.call_count == 2
    first_call_pages = mock_sink.flush.call_args_list[0][0][0]
    assert len(first_call_pages) == 3
    second_call_pages = mock_sink.flush.call_args_list[1][0][0]
    assert len(second_call_pages) == 2

    # 반환값은 빈 리스트
    assert pages == []
    assert blocks == []
