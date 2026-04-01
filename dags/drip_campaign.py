"""Airflow DAG: 온보딩 드립 캠페인.

매일 09:00 KST에 실행하여 Day 1, 3, 7 대상 유저에게 Slack DM을 발송한다.
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
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    dag_id="drip_campaign",
    default_args=default_args,
    description="온보딩 드립 캠페인: Day 1, 3, 7에 Slack DM 자동 발송",
    schedule_interval="0 0 * * *",  # 매일 00:00 UTC (= 09:00 KST)
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["onboarding", "drip", "slack"],
)


def ensure_table(**context) -> None:
    """raw_drip_users 테이블을 생성한다 (없으면)."""
    from google.cloud import bigquery

    from pipeline.drip.drip_sender import ensure_drip_table

    project_id = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ.get("BQ_DATASET", "onboarding_agent")
    bq_client = bigquery.Client(project=project_id)
    ensure_drip_table(bq_client, project_id, dataset)
    bq_client.close()


def send_drip_messages(**context) -> int:
    """대상 유저를 조회하고 드립 메시지를 전송한다."""
    from google.cloud import bigquery
    from slack_sdk import WebClient

    from pipeline.drip.drip_sender import (
        build_drip_message,
        find_due_users,
        mark_sent,
        send_drip_message,
    )

    project_id = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ.get("BQ_DATASET", "onboarding_agent")
    slack_bot_token = os.environ.get("SLACK_BOT_TOKEN", "")

    if not slack_bot_token:
        logger.warning("SLACK_BOT_TOKEN not set, skipping drip campaign")
        return 0

    bq_client = bigquery.Client(project=project_id)
    slack_client = WebClient(token=slack_bot_token)

    due_users = find_due_users(bq_client, project_id, dataset)
    sent_count = 0

    for user in due_users:
        try:
            message = build_drip_message(user["category"], user["drip_day"])
            send_drip_message(slack_client, user["slack_user_id"], message)
            mark_sent(bq_client, project_id, dataset, user["user_id"], user["drip_day"])
            sent_count += 1
        except Exception:
            logger.exception("drip send failed user=%s day=%d", user["user_id"], user["drip_day"])

    logger.info("drip campaign completed: %d/%d sent", sent_count, len(due_users))
    bq_client.close()
    return sent_count


t_ensure = PythonOperator(
    task_id="ensure_drip_table",
    python_callable=ensure_table,
    dag=dag,
)

t_send = PythonOperator(
    task_id="send_drip_messages",
    python_callable=send_drip_messages,
    dag=dag,
)

t_ensure >> t_send
