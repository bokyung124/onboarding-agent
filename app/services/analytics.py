"""검색 이벤트를 BigQuery에 비동기 로깅한다."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from functools import partial

from google.cloud import bigquery

logger = logging.getLogger(__name__)

_TABLE_SCHEMA = [
    bigquery.SchemaField("search_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("user_id", "STRING"),
    bigquery.SchemaField("query", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("category", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("is_onboarding", "BOOLEAN", mode="REQUIRED"),
    bigquery.SchemaField("chunks_retrieved", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("sources_count", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("latency_ms", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("success", "BOOLEAN", mode="REQUIRED"),
    bigquery.SchemaField("client_name", "STRING"),
    bigquery.SchemaField("tags", "STRING"),
    bigquery.SchemaField("answer", "STRING"),
]


class SearchAnalytics:
    """검색 로그를 버퍼링하여 BigQuery에 batch insert한다."""

    def __init__(
        self,
        bq_client: bigquery.Client,
        project_id: str,
        dataset: str,
        table: str = "analytics_search_logs",
        buffer_size: int = 5,
    ):
        self._client = bq_client
        self._table_id = f"{project_id}.{dataset}.{table}"
        self._buffer: list[dict] = []
        self._buffer_size = buffer_size
        self._lock = asyncio.Lock()

    async def log_search(
        self,
        query: str,
        category: str,
        chunks_retrieved: int,
        sources_count: int,
        latency_ms: int,
        is_onboarding: bool = False,
        user_id: str | None = None,
        success: bool = True,
        client_name: str | None = None,
        tags: str | None = None,
        answer: str | None = None,
    ) -> None:
        """검색 이벤트를 버퍼에 추가한다. 버퍼가 가득 차면 자동 flush."""
        row = {
            "search_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "query": query,
            "category": category,
            "is_onboarding": is_onboarding,
            "chunks_retrieved": chunks_retrieved,
            "sources_count": sources_count,
            "latency_ms": latency_ms,
            "success": success,
            "client_name": client_name,
            "tags": tags,
            "answer": answer[:5000] if answer else None,
        }
        async with self._lock:
            self._buffer.append(row)
            if len(self._buffer) >= self._buffer_size:
                await self._flush_locked()

    async def flush(self) -> int:
        """버퍼의 모든 로그를 BigQuery에 적재한다."""
        async with self._lock:
            return await self._flush_locked()

    async def _flush_locked(self) -> int:
        """lock 보유 상태에서 flush를 수행한다."""
        if not self._buffer:
            return 0
        rows = self._buffer.copy()
        self._buffer.clear()

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, partial(self._insert_rows, rows))
            logger.info("analytics flush rows=%d", len(rows))
        except Exception:
            logger.exception("analytics flush failed rows=%d", len(rows))
            # 실패한 로그는 버림 (검색에 영향 주지 않음)
        return len(rows)

    def _insert_rows(self, rows: list[dict]) -> None:
        """BigQuery에 행을 삽입한다 (동기)."""
        errors = self._client.insert_rows_json(self._table_id, rows)
        if errors:
            raise RuntimeError(f"BigQuery insert errors: {errors}")

    async def ensure_table(self) -> None:
        """analytics_search_logs 테이블이 없으면 생성한다."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._create_table_if_not_exists)

    def _create_table_if_not_exists(self) -> None:
        table = bigquery.Table(self._table_id, schema=_TABLE_SCHEMA)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="timestamp",
        )
        try:
            self._client.create_table(table, exists_ok=True)
            logger.info("analytics table ensured: %s", self._table_id)
            self._patch_schema_if_needed()
        except Exception:
            logger.exception("analytics table creation failed: %s", self._table_id)

    def _patch_schema_if_needed(self) -> None:
        """기존 테이블에 누락된 컬럼이 있으면 추가한다."""
        try:
            existing = self._client.get_table(self._table_id)
            existing_names = {f.name for f in existing.schema}
            new_fields = [f for f in _TABLE_SCHEMA if f.name not in existing_names]
            if new_fields:
                updated_schema = list(existing.schema) + new_fields
                existing.schema = updated_schema
                self._client.update_table(existing, ["schema"])
                logger.info(
                    "analytics schema patched: added %s",
                    [f.name for f in new_fields],
                )
        except Exception:
            logger.exception("analytics schema patch failed: %s", self._table_id)
