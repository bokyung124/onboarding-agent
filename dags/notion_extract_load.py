"""Airflow DAG: Notion 전체 워크스페이스를 BigQuery raw 테이블에 적재한다.

스케줄: 매일 06:00 KST (21:00 UTC)
"""

import json
import logging
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator

logger = logging.getLogger(__name__)

# ── DAG 설정 ──────────────────────────────────────────────────────────────

default_args = {
    "owner": "data-engineering",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    dag_id="notion_extract_load",
    default_args=default_args,
    description="Notion 워크스페이스에서 페이지/블록/데이터베이스를 추출하여 BigQuery에 적재",
    schedule_interval="0 21 * * *",  # 매일 06:00 KST
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["notion", "extract", "bigquery"],
)


# ── Task 함수 ─────────────────────────────────────────────────────────────


def get_checkpoint(**context) -> str | None:
    """마지막 추출 시점을 가져온다 (XCom 또는 BigQuery에서)."""
    from google.cloud import bigquery

    project_id = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ.get("BQ_DATASET", "onboarding_agent")
    client = bigquery.Client(project=project_id)

    query = f"""
    SELECT MAX(_extracted_at) as last_extracted
    FROM `{project_id}.{dataset}.raw_notion_pages`
    """
    try:
        result = list(client.query(query).result())
        if result and result[0].last_extracted:
            # 5분 overlap으로 누락 방지
            checkpoint = result[0].last_extracted - timedelta(minutes=5)
            checkpoint_str = checkpoint.isoformat()
            logger.info("Checkpoint: %s", checkpoint_str)
            return checkpoint_str
    except Exception:
        logger.info("No checkpoint found, performing full extraction")
    return None


def extract_notion(**context) -> dict:
    """Notion API에서 데이터를 추출한다."""
    import asyncio

    from pipeline.extract.notion_extractor import NotionExtractor

    api_key = os.environ["NOTION_API_KEY"]
    root_page_id = os.environ.get("NOTION_ROOT_PAGE_ID")
    checkpoint = context["ti"].xcom_pull(task_ids="get_checkpoint")

    async def _extract():
        extractor = NotionExtractor(api_key=api_key, root_page_id=root_page_id or None)
        try:
            pages, blocks, databases, comments = await extractor.crawl_all(since=checkpoint)
            return {"pages": pages, "blocks": blocks, "databases": databases, "comments": comments}
        finally:
            await extractor.close()

    result = asyncio.run(_extract())
    logger.info(
        "Extracted: %d pages, %d blocks, %d databases, %d comments",
        len(result["pages"]),
        len(result["blocks"]),
        len(result["databases"]),
        len(result["comments"]),
    )
    return result


def load_to_bigquery(**context) -> None:
    """추출된 데이터를 BigQuery raw 테이블에 적재한다."""
    from google.cloud import bigquery

    project_id = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ.get("BQ_DATASET", "onboarding_agent")
    client = bigquery.Client(project=project_id)

    data = context["ti"].xcom_pull(task_ids="extract_notion")
    if not data:
        logger.warning("No data to load")
        return

    table_mapping = {
        "pages": f"{project_id}.{dataset}.raw_notion_pages",
        "blocks": f"{project_id}.{dataset}.raw_notion_blocks",
        "databases": f"{project_id}.{dataset}.raw_notion_databases",
        "comments": f"{project_id}.{dataset}.raw_notion_comments",
    }

    for key, table_id in table_mapping.items():
        records = data.get(key, [])
        if not records:
            logger.info("No %s to load", key)
            continue

        # JSON 필드를 문자열로 변환 (BigQuery JSON 타입 호환)
        for record in records:
            for field in ("properties_json", "schema_json"):
                if field in record and isinstance(record[field], dict):
                    record[field] = json.dumps(record[field], ensure_ascii=False)

        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            autodetect=True,
        )

        job = client.load_table_from_json(records, table_id, job_config=job_config)
        job.result()  # 완료 대기
        logger.info("Loaded %d %s to %s", len(records), key, table_id)


# ── Task 정의 ─────────────────────────────────────────────────────────────

t_checkpoint = PythonOperator(
    task_id="get_checkpoint",
    python_callable=get_checkpoint,
    dag=dag,
)

t_extract = PythonOperator(
    task_id="extract_notion",
    python_callable=extract_notion,
    dag=dag,
)

t_load = PythonOperator(
    task_id="load_to_bigquery",
    python_callable=load_to_bigquery,
    dag=dag,
)

t_trigger_embed = TriggerDagRunOperator(
    task_id="trigger_embed",
    trigger_dag_id="enterprise_embed",
    dag=dag,
)

t_checkpoint >> t_extract >> t_load >> t_trigger_embed
