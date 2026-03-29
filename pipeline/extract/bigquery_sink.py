"""BigQuery 배치 적재 sink — 추출 데이터를 배치 단위로 BigQuery에 flush한다."""

import asyncio
import json
import logging
from functools import partial

from google.cloud import bigquery

logger = logging.getLogger(__name__)


class BigQueryBatchSink:
    """추출 배치를 BigQuery raw 테이블에 적재한다.

    풀 리프레시 모드(WRITE_TRUNCATE)에서는 첫 flush에서만 TRUNCATE하고
    이후 flush부터 자동으로 WRITE_APPEND로 전환한다.
    """

    def __init__(
        self,
        project_id: str,
        dataset: str,
        write_disposition: str = "WRITE_APPEND",
    ) -> None:
        self._client = bigquery.Client(project=project_id)
        self._project_id = project_id
        self._dataset = dataset
        self._initial_disposition = getattr(bigquery.WriteDisposition, write_disposition)
        self._table_first_flush: dict[str, bool] = {}
        self.total_pages = 0
        self.total_blocks = 0
        self.total_databases = 0
        self.total_comments = 0

    async def flush(
        self,
        pages: list[dict],
        blocks: list[dict],
        databases: list[dict],
        comments: list[dict],
    ) -> None:
        """배치 데이터를 BigQuery에 적재한다."""
        # JSON 필드 직렬화
        for p in pages:
            if isinstance(p.get("properties_json"), dict):
                p["properties_json"] = json.dumps(p["properties_json"], ensure_ascii=False)
        for db in databases:
            if isinstance(db.get("schema_json"), dict):
                db["schema_json"] = json.dumps(db["schema_json"], ensure_ascii=False)

        table_mapping = {
            "raw_notion_pages": pages,
            "raw_notion_blocks": blocks,
            "raw_notion_databases": databases,
            "raw_notion_comments": comments,
        }

        loop = asyncio.get_event_loop()
        for table_name, data in table_mapping.items():
            if not data:
                continue
            # 테이블별 첫 load에서만 초기 disposition 사용, 이후 APPEND
            if table_name not in self._table_first_flush:
                disposition = self._initial_disposition
                self._table_first_flush[table_name] = True
            else:
                disposition = bigquery.WriteDisposition.WRITE_APPEND
            table_ref = f"{self._project_id}.{self._dataset}.{table_name}"
            job_config = bigquery.LoadJobConfig(
                write_disposition=disposition,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                autodetect=True,
            )
            await loop.run_in_executor(
                None,
                partial(self._load, table_ref, data, job_config),
            )

        self.total_pages += len(pages)
        self.total_blocks += len(blocks)
        self.total_databases += len(databases)
        self.total_comments += len(comments)
        logger.info(
            "Flushed batch: %d pages, %d blocks, %d dbs, %d comments (total: %d/%d/%d/%d)",
            len(pages),
            len(blocks),
            len(databases),
            len(comments),
            self.total_pages,
            self.total_blocks,
            self.total_databases,
            self.total_comments,
        )

    def _load(self, table_ref: str, data: list[dict], job_config: bigquery.LoadJobConfig) -> None:
        job = self._client.load_table_from_json(data, table_ref, job_config=job_config)
        job.result()

    def close(self) -> None:
        self._client.close()
