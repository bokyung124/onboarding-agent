"""Airflow DAG: dbt 변환 완료 후 변경된 청크에 Gemini 임베딩을 생성한다."""

import logging
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

default_args = {
    "owner": "data-engineering",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=3),
}

dag = DAG(
    dag_id="notion_embed",
    default_args=default_args,
    description="dbt 변환 완료 후 변경된 청크에 Gemini 임베딩 생성 및 BigQuery 적재",
    schedule_interval=None,  # notion_extract_load DAG에서 트리거
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["notion", "embedding", "gemini", "bigquery"],
)


def run_dbt(**context) -> None:
    """dbt run을 실행한다."""
    import subprocess

    result = subprocess.run(
        ["dbt", "run", "--project-dir", "dbt_notion", "--profiles-dir", "dbt_notion"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("dbt run failed:\n%s", result.stderr)
        raise RuntimeError(f"dbt run failed: {result.stderr}")
    logger.info("dbt run completed:\n%s", result.stdout)


def detect_and_embed(**context) -> int:
    """변경된 청크를 감지하고 임베딩을 생성한다."""
    from google import genai
    from google.cloud import bigquery

    from pipeline.embed.generate_embeddings import (
        detect_changed_chunks,
        generate_embeddings,
        load_vectors_to_bigquery,
    )

    project_id = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ.get("BQ_DATASET", "onboarding_agent")
    gemini_api_key = os.environ["GEMINI_API_KEY"]

    bq_client = bigquery.Client(project=project_id)
    genai_client = genai.Client(api_key=gemini_api_key)

    # 1. 변경된 청크 감지
    changed_chunks = detect_changed_chunks(bq_client, project_id, dataset)
    if not changed_chunks:
        logger.info("No changed chunks to embed")
        return 0

    # 2. 임베딩 생성
    vectors = generate_embeddings(genai_client, changed_chunks)

    # 3. BigQuery에 적재
    load_vectors_to_bigquery(bq_client, project_id, dataset, vectors)

    return len(vectors)


t_dbt = PythonOperator(
    task_id="run_dbt",
    python_callable=run_dbt,
    dag=dag,
)

t_embed = PythonOperator(
    task_id="detect_and_embed",
    python_callable=detect_and_embed,
    dag=dag,
)

t_dbt >> t_embed
