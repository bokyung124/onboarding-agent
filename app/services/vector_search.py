"""BigQuery VECTOR_SEARCH를 호출하여 유사한 청크를 검색한다."""

import asyncio
from functools import partial

from google.cloud import bigquery

from app.config import Settings
from app.models.domain import ChunkResult


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
    ) -> list[ChunkResult]:
        """벡터 유사도 검색 후 카테고리 필터링하여 결과를 반환한다."""
        top_k = top_k or self._settings.search_top_k
        result_limit = result_limit or self._settings.search_result_limit

        project = self._settings.gcp_project_id
        dataset = self._settings.bq_mart_dataset
        table = self._settings.bq_vectors_table

        # category가 "all"이면 필터 없이 전체 검색
        where_clause = ""
        query_params = [
            bigquery.ArrayQueryParameter("query_embedding", "FLOAT64", query_embedding),
        ]
        if category != "all":
            where_clause = "WHERE base.category = @category"
            query_params.append(
                bigquery.ScalarQueryParameter("category", "STRING", category),
            )

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
            distance
        FROM VECTOR_SEARCH(
            TABLE `{project}.{dataset}.{table}`,
            'embedding',
            (SELECT @query_embedding AS embedding),
            top_k => {top_k},
            distance_type => 'COSINE'
        )
        {where_clause}
        ORDER BY distance ASC
        LIMIT {result_limit}
        """

        job_config = bigquery.QueryJobConfig(query_parameters=query_params)

        # BigQuery 클라이언트는 동기 → executor로 async 래핑
        loop = asyncio.get_event_loop()
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
            )
            for row in rows
        ]

    def _execute_query(self, query: str, job_config: bigquery.QueryJobConfig) -> list:
        return list(self._client.query(query, job_config=job_config).result())
