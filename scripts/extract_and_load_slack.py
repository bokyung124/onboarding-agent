"""Slack 데이터를 추출하여 BigQuery에 적재하는 스크립트.

환경변수:
    EXTRACT_MODE: "full" (기본, WRITE_TRUNCATE) | "incremental" (WRITE_APPEND, since 사용)
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from google.cloud import bigquery

from pipeline.extract.slack_extractor import SlackExtractor

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def get_slack_checkpoint(project_id: str, dataset: str) -> str | None:
    """BigQuery raw_slack_messages에서 마지막 추출 시점을 조회한다.

    Returns:
        Unix timestamp 문자열 (e.g. "1234567890.0") 또는 None.
    """
    bq = bigquery.Client(project=project_id)
    query = f"""
    SELECT MAX(
        TIMESTAMP_SECONDS(CAST(FLOOR(ts) AS INT64))
    ) as last_ts
    FROM `{project_id}.{dataset}.raw_slack_messages`
    """
    try:
        result = list(bq.query(query).result())
        if result and result[0].last_ts:
            checkpoint = result[0].last_ts - timedelta(minutes=5)
            checkpoint_ts = str(checkpoint.timestamp())
            logging.info("Slack checkpoint: %s", checkpoint_ts)
            return checkpoint_ts
    except Exception:
        logging.warning("Checkpoint query failed", exc_info=True)
    finally:
        bq.close()
    return None


async def main() -> None:
    bot_token = os.getenv("SLACK_BOT_TOKEN")
    project_id = os.getenv("GCP_PROJECT_ID")
    dataset = os.getenv("BQ_DATASET", "onboarding_agent")
    workspace = os.getenv("SLACK_WORKSPACE", "")

    mode = os.getenv("EXTRACT_MODE", "full")
    channel_ids_raw = os.getenv("SLACK_CHANNEL_IDS", "")
    channel_ids = [c.strip() for c in channel_ids_raw.split(",") if c.strip()] or None

    # 증분 모드: SINCE_DATE 환경변수 우선, 없으면 BQ checkpoint 조회
    since_ts: str | None = None
    if mode == "incremental":
        since_date = os.getenv("SINCE_DATE")  # YYYY-MM-DD
        if since_date:
            dt = datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            since_ts = str(dt.timestamp())
            logging.info(
                "Incremental mode (manual): since_date=%s, since_ts=%s",
                since_date,
                since_ts,
            )
        else:
            since_ts = get_slack_checkpoint(project_id, dataset)
            logging.info("Incremental mode (checkpoint): since_ts=%s", since_ts)
    else:
        logging.info("Full mode: WRITE_TRUNCATE")

    bq = bigquery.Client(project=project_id)
    messages_table = f"{project_id}.{dataset}.raw_slack_messages"
    first_flush = True

    async def flush_channel(messages: list[dict]) -> None:
        nonlocal first_flush
        if not messages:
            return
        # 기존 테이블 스키마가 FLOAT이므로 타입 맞춤
        for m in messages:
            m["ts"] = float(m["ts"])
            if m.get("thread_ts") is not None:
                m["thread_ts"] = float(m["thread_ts"])
        if mode == "incremental":
            disposition = bigquery.WriteDisposition.WRITE_APPEND
        else:
            disposition = (
                bigquery.WriteDisposition.WRITE_TRUNCATE
                if first_flush
                else bigquery.WriteDisposition.WRITE_APPEND
            )
        first_flush = False
        loop = asyncio.get_event_loop()
        job_config = bigquery.LoadJobConfig(
            write_disposition=disposition,
        )
        await loop.run_in_executor(
            None,
            lambda: bq.load_table_from_json(
                messages, messages_table, job_config=job_config
            ).result(),
        )
        logging.info("  raw_slack_messages: %d rows flushed", len(messages))

    # 1. Slack 추출 (채널별 즉시 BQ flush)
    logging.info("Extracting from Slack...")
    extractor = SlackExtractor(
        bot_token=bot_token,
        channel_ids=channel_ids,
        workspace=workspace,
    )
    try:
        _, users = await extractor.extract_all(since_ts=since_ts, on_channel_done=flush_channel)
    finally:
        await extractor.close()

    if first_flush:
        logging.warning("No messages extracted!")

    # 2. 유저 적재
    if users:
        users_table = f"{project_id}.{dataset}.raw_slack_users"
        job = bq.load_table_from_json(
            users,
            users_table,
            job_config=bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                autodetect=True,
            ),
        )
        job.result()
        logging.info("  raw_slack_users: %d rows loaded", len(users))

    bq.close()
    logging.info("Done!")


if __name__ == "__main__":
    asyncio.run(main())
