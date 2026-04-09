"""Airflow DAG: dbt 변환 완료 후 통합 청크에 Gemini 임베딩을 생성한다.

notion_extract_load 또는 slack_extract_load DAG에서 트리거된다.
Notion + Slack 모든 소스의 변경된 청크를 감지하여 임베딩을 생성한다.
"""

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
    dag_id="enterprise_embed",
    default_args=default_args,
    description="dbt 변환 후 Notion+Slack 통합 청크에 Gemini 임베딩 생성 및 BigQuery 적재",
    schedule_interval=None,  # 트리거 전용
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["enterprise", "embedding", "gemini", "bigquery"],
)


def run_dbt(**context) -> None:
    """dbt run을 실행한다 (Notion + Slack 모델 모두)."""
    import subprocess

    dag_dir = os.path.dirname(os.path.abspath(__file__))
    dbt_project_dir = os.path.join(dag_dir, "dbt_notion")
    result = subprocess.run(
        ["dbt", "run", "--project-dir", dbt_project_dir, "--profiles-dir", dbt_project_dir],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("dbt run failed:\n%s", result.stderr)
        raise RuntimeError(f"dbt run failed: {result.stderr}")
    logger.info("dbt run completed:\n%s", result.stdout)


def detect_and_embed(**context) -> int:
    """통합 mart에서 변경된 청크를 감지하고 임베딩을 생성한다."""
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

    changed_chunks = detect_changed_chunks(bq_client, project_id, dataset)
    if not changed_chunks:
        logger.info("No changed chunks to embed")
        return 0

    vectors = generate_embeddings(genai_client, changed_chunks)
    load_vectors_to_bigquery(bq_client, project_id, dataset, vectors)

    return len(vectors)


def sync_metadata(**context) -> int:
    """dbt에서 변경된 메타데이터(category 등)를 vectors 테이블에 동기화한다."""
    from google.cloud import bigquery

    from pipeline.embed.generate_embeddings import sync_metadata_from_chunks

    project_id = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ.get("BQ_DATASET", "onboarding_agent")
    bq_client = bigquery.Client(project=project_id)

    return sync_metadata_from_chunks(bq_client, project_id, dataset)


def create_vector_index(**context) -> None:
    """mart_enterprise_vectors에 IVF 벡터 인덱스가 없으면 생성한다."""
    from google.cloud import bigquery

    from pipeline.embed.generate_embeddings import ensure_vector_index

    project_id = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ.get("BQ_DATASET", "onboarding_agent")
    bq_client = bigquery.Client(project=project_id)

    ensure_vector_index(bq_client, project_id, dataset)


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

t_ensure_index = PythonOperator(
    task_id="ensure_vector_index",
    python_callable=create_vector_index,
    dag=dag,
)

t_sync_metadata = PythonOperator(
    task_id="sync_metadata",
    python_callable=sync_metadata,
    dag=dag,
)

t_dbt >> t_sync_metadata >> t_embed >> t_ensure_index
