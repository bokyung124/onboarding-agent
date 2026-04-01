"""BigQuery VECTOR_SEARCH를 호출하여 유사한 청크를 검색한다."""

import asyncio
import logging
from functools import partial

from google.cloud import bigquery

from app.config import Settings
from app.models.domain import ChunkResult

logger = logging.getLogger(__name__)


class VectorSearchService:
    def __init__(self, bq_client: bigquery.Client, settings: Settings):
        self._client = bq_client
        self._settings = settings

    async def search(
        self,
        query_embedding: list[float],
        category: str = "all",
        top_k: int | None = None,
        result_limit: int | None = None,
        client_name: str | None = None,
        tags: str | None = None,
        is_onboarding: bool = False,
    ) -> list[ChunkResult]:
        """BigQuery VECTOR_SEARCH로 유사 청크를 검색한다."""
        # 카테고리 필터 시 post-filter로 걸러지므로 top_k를 넉넉히 확보
        default_top_k = self._settings.search_top_k
        if category != "all":
            default_top_k = default_top_k * 3
        top_k = top_k or default_top_k
        result_limit = result_limit or self._settings.search_result_limit

        project = self._settings.gcp_project_id
        dataset = self._settings.bq_mart_dataset
        table = self._settings.bq_vectors_table

        query_params = [
            bigquery.ArrayQueryParameter("query_embedding", "FLOAT64", query_embedding),
            bigquery.ScalarQueryParameter(
                "distance_threshold",
                "FLOAT64",
                self._settings.search_distance_threshold,
            ),
        ]

        # 항상 TABLE 참조로 IVF 인덱스를 활용하고, post-filter로 카테고리 필터링
        table_expr = f"TABLE `{project}.{dataset}.{table}`"

        # Post-filter 조건
        post_filter_conditions: list[str] = ["distance <= @distance_threshold"]
        if category != "all":
            post_filter_conditions.append("base.category = @category")
            query_params.append(bigquery.ScalarQueryParameter("category", "STRING", category))
        if client_name:
            post_filter_conditions.append("base.client_name = @client_name")
            query_params.append(bigquery.ScalarQueryParameter("client_name", "STRING", client_name))
        if tags:
            post_filter_conditions.append("base.tags LIKE @tags_pattern")
            query_params.append(
                bigquery.ScalarQueryParameter("tags_pattern", "STRING", f"%{tags}%")
            )
        if is_onboarding:
            post_filter_conditions.append("base.is_onboarding = TRUE")
        post_filter_where = " AND ".join(post_filter_conditions)

        fraction = self._settings.search_fraction_lists

        # 벡터 검색만 수행 (CTE/JOIN 제거로 IVF 인덱스 최적화 보장)
        query = f"""
        SELECT
            base.chunk_id,
            base.page_id,
            base.page_title,
            base.breadcrumb_path,
            base.category,
            base.chunk_text,
            base.notion_url AS source_url,
            base.source_type,
            base.last_edited_at,
            base.client_name,
            base.tags,
            distance
        FROM VECTOR_SEARCH(
            {table_expr},
            'embedding',
            (SELECT @query_embedding AS embedding),
            top_k => {top_k},
            distance_type => 'COSINE',
            options => '{{"fraction_lists_to_search": {fraction}}}'
        )
        WHERE {post_filter_where}
        ORDER BY distance ASC
        LIMIT {result_limit}
        """

        job_config = bigquery.QueryJobConfig(query_parameters=query_params)

        loop = asyncio.get_running_loop()
        rows = await loop.run_in_executor(None, partial(self._execute_query, query, job_config))

        return [
            ChunkResult(
                chunk_id=row.chunk_id,
                page_id=row.page_id,
                page_title=row.page_title,
                breadcrumb=row.breadcrumb_path,
                category=row.category,
                content=row.chunk_text,
                source_url=row.source_url,
                source_type=row.source_type,
                distance=row.distance,
                last_edited_at=(str(row.last_edited_at) if row.last_edited_at else None),
                client_name=row.client_name or None,
                tags=row.tags or None,
            )
            for row in rows
        ]

    @property
    def result_limit(self) -> int:
        return self._settings.search_result_limit

    def _execute_query(self, query: str, job_config: bigquery.QueryJobConfig) -> list:
        job = self._client.query(query, job_config=job_config)
        rows = list(job.result())
        logger.info(
            "bq_stats slot_ms=%s bytes=%s stages=%d rows=%d",
            job.slot_millis,
            job.total_bytes_processed,
            len(job.query_plan) if job.query_plan else 0,
            len(rows),
        )
        return rows
