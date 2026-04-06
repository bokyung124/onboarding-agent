"""BigQuery mart_enterprise_chunks에서 변경된 청크를 감지하고 Gemini 임베딩을 생성한다."""

import logging
from datetime import datetime, timezone

from google import genai
from google.cloud import bigquery
from google.genai import types

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "gemini-embedding-2-preview"
EMBEDDING_DIMENSIONS = 768
BATCH_SIZE = 100  # Gemini embedding API 배치 제한


def _table_exists(bq_client: bigquery.Client, table_ref: str) -> bool:
    """BigQuery 테이블 존재 여부를 확인한다."""
    try:
        bq_client.get_table(table_ref)
        return True
    except Exception:
        return False


def detect_changed_chunks(bq_client: bigquery.Client, project_id: str, dataset: str) -> list[dict]:
    """mart_enterprise_chunks에서 신규 또는 변경된 청크를 감지한다."""
    mart_dataset = f"{dataset}_mart_notion"
    vectors_table = f"{project_id}.{mart_dataset}.mart_enterprise_vectors"

    if _table_exists(bq_client, vectors_table):
        # 증분: 신규 또는 변경된 청크만
        query = f"""
        SELECT
            c.chunk_id, c.page_id, c.page_title, c.breadcrumb_path,
            c.category, c.is_onboarding, c.notion_url, c.client_name, c.tags,
            c.chunk_text, c.section_number, c.last_edited_at, c.source_type
        FROM `{project_id}.{mart_dataset}.mart_enterprise_chunks` c
        LEFT JOIN `{vectors_table}` v
            ON c.chunk_id = v.chunk_id
        WHERE v.chunk_id IS NULL
           OR c.last_edited_at > v._embedded_at
           OR c.category != v.category
           OR c.is_onboarding != v.is_onboarding
        """
    else:
        # 첫 실행: 전체 청크
        logger.info("Vectors table not found — full embedding run")
        query = f"""
        SELECT
            chunk_id, page_id, page_title, breadcrumb_path,
            category, is_onboarding, notion_url, client_name, tags,
            chunk_text, section_number, last_edited_at, source_type
        FROM `{project_id}.{mart_dataset}.mart_enterprise_chunks`
        """

    rows = list(bq_client.query(query).result())
    logger.info("Changed chunks detected: %d", len(rows))
    return [dict(row) for row in rows]


def generate_embeddings(
    genai_client: genai.Client,
    chunks: list[dict],
) -> list[dict]:
    """청크 텍스트에 대한 Gemini 임베딩을 배치로 생성한다."""
    if not chunks:
        return []

    embedded_at = datetime.now(timezone.utc).isoformat()
    results: list[dict] = []

    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]
        texts = [c["chunk_text"] for c in batch]

        response = genai_client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=EMBEDDING_DIMENSIONS,
            ),
        )

        for j, embedding in enumerate(response.embeddings):
            chunk = batch[j]
            results.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "page_id": chunk["page_id"],
                    "page_title": chunk["page_title"],
                    "breadcrumb_path": chunk["breadcrumb_path"],
                    "category": chunk["category"],
                    "is_onboarding": chunk.get("is_onboarding", False),
                    "notion_url": chunk["notion_url"],
                    "client_name": chunk.get("client_name", ""),
                    "tags": chunk.get("tags", ""),
                    "chunk_text": chunk["chunk_text"],
                    "section_number": chunk.get("section_number"),
                    "source_type": chunk.get("source_type", "notion"),
                    "embedding": embedding.values,
                    "last_edited_at": chunk.get("last_edited_at").isoformat()
                    if hasattr(chunk.get("last_edited_at"), "isoformat")
                    else chunk.get("last_edited_at"),
                    "_embedded_at": embedded_at,
                }
            )

        logger.info("Embedded batch %d-%d / %d", i, i + len(batch), len(chunks))

    return results


def load_vectors_to_bigquery(
    bq_client: bigquery.Client,
    project_id: str,
    dataset: str,
    vectors: list[dict],
) -> None:
    """벡터를 BigQuery에 MERGE(upsert)로 적재한다."""
    if not vectors:
        return

    mart_dataset = f"{dataset}_mart_notion"
    vectors_table = f"{project_id}.{mart_dataset}.mart_enterprise_vectors"
    staging_table = f"{project_id}.{mart_dataset}._staging_vectors"

    # 스테이징 테이블에 먼저 적재
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        autodetect=True,
    )
    job = bq_client.load_table_from_json(vectors, staging_table, job_config=job_config)
    job.result()
    logger.info("Loaded %d vectors to staging", len(vectors))

    if not _table_exists(bq_client, vectors_table):
        # 첫 실행: 스테이징 테이블을 vectors 테이블로 복사
        copy_query = f"""
        CREATE TABLE `{vectors_table}` AS
        SELECT * FROM `{staging_table}`
        """
        bq_client.query(copy_query).result()
        logger.info("Created %s with %d vectors", vectors_table, len(vectors))
    else:
        # MERGE로 upsert
        merge_query = f"""
        MERGE `{vectors_table}` T
        USING `{staging_table}` S
        ON T.chunk_id = S.chunk_id
        WHEN MATCHED THEN
            UPDATE SET
                page_title = S.page_title,
                breadcrumb_path = S.breadcrumb_path,
                category = S.category,
                is_onboarding = S.is_onboarding,
                notion_url = S.notion_url,
                client_name = S.client_name,
                tags = S.tags,
                chunk_text = S.chunk_text,
                section_number = S.section_number,
                source_type = S.source_type,
                embedding = S.embedding,
                last_edited_at = S.last_edited_at,
                _embedded_at = S._embedded_at
        WHEN NOT MATCHED THEN
            INSERT (chunk_id, page_id, page_title, breadcrumb_path, category,
                    is_onboarding, notion_url, client_name, tags, chunk_text,
                    section_number, source_type, embedding, last_edited_at, _embedded_at)
            VALUES (S.chunk_id, S.page_id, S.page_title, S.breadcrumb_path, S.category,
                    S.is_onboarding, S.notion_url, S.client_name, S.tags, S.chunk_text,
                    S.section_number, S.source_type, S.embedding, S.last_edited_at, S._embedded_at)
        """
        bq_client.query(merge_query).result()
        logger.info("Merged %d vectors into %s", len(vectors), vectors_table)


def sync_metadata_from_chunks(
    bq_client: bigquery.Client,
    project_id: str,
    dataset: str,
) -> int:
    """mart_enterprise_chunks의 메타데이터(category, is_onboarding 등)를 vectors에 동기화한다.

    임베딩 재생성 없이 category 등 메타데이터 변경만 반영할 때 사용한다.
    """
    mart_dataset = f"{dataset}_mart_notion"
    vectors_table = f"{project_id}.{mart_dataset}.mart_enterprise_vectors"
    chunks_table = f"{project_id}.{mart_dataset}.mart_enterprise_chunks"

    if not _table_exists(bq_client, vectors_table):
        logger.info("Vectors table does not exist — skipping metadata sync")
        return 0

    query = f"""
    UPDATE `{vectors_table}` v
    SET
        v.category = c.category,
        v.is_onboarding = c.is_onboarding,
        v.page_title = c.page_title,
        v.breadcrumb_path = c.breadcrumb_path,
        v.client_name = c.client_name,
        v.tags = c.tags
    FROM `{chunks_table}` c
    WHERE v.chunk_id = c.chunk_id
      AND (v.category != c.category
           OR v.is_onboarding != c.is_onboarding
           OR v.page_title != c.page_title
           OR v.breadcrumb_path != c.breadcrumb_path
           OR IFNULL(v.client_name, '') != IFNULL(c.client_name, '')
           OR IFNULL(v.tags, '') != IFNULL(c.tags, ''))
    """
    job = bq_client.query(query)
    job.result()
    updated = job.num_dml_affected_rows or 0
    logger.info("Metadata sync: updated %d vectors", updated)
    return updated


def ensure_vector_index(
    bq_client: bigquery.Client,
    project_id: str,
    dataset: str,
) -> None:
    """mart_enterprise_vectors에 IVF 벡터 인덱스를 (재)생성한다."""
    mart_dataset = f"{dataset}_mart_notion"
    vectors_table = f"{project_id}.{mart_dataset}.mart_enterprise_vectors"

    if not _table_exists(bq_client, vectors_table):
        logger.info("Vectors table does not exist yet — skipping index creation")
        return

    ddl = f"""
    CREATE OR REPLACE VECTOR INDEX idx_enterprise_vectors_embedding
    ON `{vectors_table}`(embedding)
    STORING (category, is_onboarding, client_name, tags)
    OPTIONS (
        index_type = 'IVF',
        distance_type = 'COSINE',
        ivf_options = '{{"num_lists": 100}}'
    )
    """
    bq_client.query(ddl).result()
    logger.info("Vector index ensured on %s", vectors_table)
