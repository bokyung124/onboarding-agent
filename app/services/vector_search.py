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
        client_name: str | None = None,
        tags: str | None = None,
    ) -> list[ChunkResult]:
        """벡터 유사도 검색 후 카테고리/메타데이터 필터링하여 결과를 반환한다."""
        top_k = top_k or self._settings.search_top_k
        result_limit = result_limit or self._settings.search_result_limit

        project = self._settings.gcp_project_id
        dataset = self._settings.bq_mart_dataset
        table = self._settings.bq_vectors_table

        where_conditions = ["distance <= @distance_threshold"]
        query_params = [
            bigquery.ArrayQueryParameter("query_embedding", "FLOAT64", query_embedding),
            bigquery.ScalarQueryParameter(
                "distance_threshold", "FLOAT64", self._settings.search_distance_threshold
            ),
        ]

        if category != "all":
            where_conditions.append("base.category = @category")
            query_params.append(bigquery.ScalarQueryParameter("category", "STRING", category))
        if client_name:
            where_conditions.append("base.client_name = @client_name")
            query_params.append(bigquery.ScalarQueryParameter("client_name", "STRING", client_name))
        if tags:
            where_conditions.append("base.tags LIKE @tags_pattern")
            query_params.append(
                bigquery.ScalarQueryParameter("tags_pattern", "STRING", f"%{tags}%")
            )

        where_clause = ("WHERE " + " AND ".join(where_conditions)) if where_conditions else ""

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
                last_edited_at=str(row.last_edited_at) if row.last_edited_at else None,
            )
            for row in rows
        ]

    async def enrich_with_parent_context(
        self, chunks: list[ChunkResult], top_n: int = 3
    ) -> list[ChunkResult]:
        """상위 top_n개 notion 청크에 부모 페이지 전체 본문(full_markdown)을 주입한다."""
        notion_chunks = [c for c in chunks[:top_n] if c.source_type == "notion"]
        if not notion_chunks:
            return chunks

        page_ids = list({c.page_id for c in notion_chunks})
        project = self._settings.gcp_project_id
        dataset = self._settings.bq_mart_dataset

        query = f"""
        SELECT page_id, full_markdown
        FROM `{project}.{dataset}.mart_notion_documents`
        WHERE page_id IN UNNEST(@page_ids)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ArrayQueryParameter("page_ids", "STRING", page_ids)]
        )

        loop = asyncio.get_running_loop()
        rows = await loop.run_in_executor(None, partial(self._execute_query, query, job_config))
        parent_map = {row.page_id: row.full_markdown for row in rows}

        return [
            chunk.model_copy(update={"parent_content": parent_map[chunk.page_id]})
            if chunk.source_type == "notion" and chunk.page_id in parent_map
            else chunk
            for chunk in chunks
        ]

    @property
    def result_limit(self) -> int:
        return self._settings.search_result_limit

    def _execute_query(self, query: str, job_config: bigquery.QueryJobConfig) -> list:
        return list(self._client.query(query, job_config=job_config).result())
