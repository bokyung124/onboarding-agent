"""Airflow DAG: Slack 채널 메시지를 BigQuery raw 테이블에 적재한다.

스케줄: 매일 06:30 KST (21:30 UTC) — notion_extract_load 30분 후
"""

import logging
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator

logger = logging.getLogger(__name__)

default_args = {
    "owner": "data-engineering",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    dag_id="slack_extract_load",
    default_args=default_args,
    description="Slack 채널 메시지와 유저 정보를 추출하여 BigQuery에 적재",
    schedule_interval="30 21 * * *",  # 매일 06:30 KST
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["slack", "extract", "bigquery"],
)


def get_checkpoint(**context) -> str | None:
    """마지막 추출 시점을 가져온다."""
    from google.cloud import bigquery

    project_id = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ.get("BQ_DATASET", "onboarding_agent")
    client = bigquery.Client(project=project_id)

    query = f"""
    SELECT MAX(
        TIMESTAMP_SECONDS(CAST(SPLIT(ts, '.')[OFFSET(0)] AS INT64))
    ) as last_extracted
    FROM `{project_id}.{dataset}.raw_slack_messages`
    """
    try:
        result = list(client.query(query).result())
        if result and result[0].last_extracted:
            # 5분 overlap으로 누락 방지
            checkpoint = result[0].last_extracted - timedelta(minutes=5)
            checkpoint_ts = str(checkpoint.timestamp())
            logger.info("Checkpoint: %s", checkpoint_ts)
            return checkpoint_ts
    except Exception:
        logger.info("No checkpoint found, performing full extraction")
    return None


def extract_slack(**context) -> dict:
    """Slack API에서 데이터를 추출한다."""
    import asyncio

    from pipeline.extract.slack_extractor import SlackExtractor

    bot_token = os.environ["SLACK_BOT_TOKEN"]
    workspace = os.environ.get("SLACK_WORKSPACE", "")
    channel_ids_raw = os.environ.get("SLACK_CHANNEL_IDS", "")
    channel_ids = [c.strip() for c in channel_ids_raw.split(",") if c.strip()] or None
    checkpoint = context["ti"].xcom_pull(task_ids="get_checkpoint")

    async def _extract():
        extractor = SlackExtractor(
            bot_token=bot_token,
            channel_ids=channel_ids,
            workspace=workspace,
        )
        try:
            messages, users = await extractor.extract_all(since_ts=checkpoint)
            return {"messages": messages, "users": users}
        finally:
            await extractor.close()

    result = asyncio.run(_extract())
    logger.info(
        "Extracted: %d messages, %d users",
        len(result["messages"]),
        len(result["users"]),
    )
    return result


def load_to_bigquery(**context) -> None:
    """추출된 데이터를 BigQuery raw 테이블에 적재한다."""
    from google.cloud import bigquery

    project_id = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ.get("BQ_DATASET", "onboarding_agent")
    client = bigquery.Client(project=project_id)

    data = context["ti"].xcom_pull(task_ids="extract_slack")
    if not data:
        logger.warning("No data to load")
        return

    table_mapping = {
        "messages": f"{project_id}.{dataset}.raw_slack_messages",
        "users": f"{project_id}.{dataset}.raw_slack_users",
    }

    for key, table_id in table_mapping.items():
        records = data.get(key, [])
        if not records:
            logger.info("No %s to load", key)
            continue

        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            autodetect=True,
        )

        job = client.load_table_from_json(records, table_id, job_config=job_config)
        job.result()
        logger.info("Loaded %d %s to %s", len(records), key, table_id)


t_checkpoint = PythonOperator(
    task_id="get_checkpoint",
    python_callable=get_checkpoint,
    dag=dag,
)

t_extract = PythonOperator(
    task_id="extract_slack",
    python_callable=extract_slack,
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
