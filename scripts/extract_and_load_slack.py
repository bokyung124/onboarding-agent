"""Slack 데이터를 추출하여 BigQuery에 적재하는 스크립트."""

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from google.cloud import bigquery

from pipeline.extract.slack_extractor import SlackExtractor

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def main() -> None:
    bot_token = os.getenv("SLACK_BOT_TOKEN")
    project_id = os.getenv("GCP_PROJECT_ID")
    dataset = os.getenv("BQ_DATASET", "onboarding_agent")
    workspace = os.getenv("SLACK_WORKSPACE", "")

    channel_ids_raw = os.getenv("SLACK_CHANNEL_IDS", "")
    channel_ids = [c.strip() for c in channel_ids_raw.split(",") if c.strip()] or None

    bq = bigquery.Client(project=project_id)
    messages_table = f"{project_id}.{dataset}.raw_slack_messages"
    first_flush = True

    async def flush_channel(messages: list[dict]) -> None:
        nonlocal first_flush
        if not messages:
            return
        disposition = (
            bigquery.WriteDisposition.WRITE_TRUNCATE if first_flush else bigquery.WriteDisposition.WRITE_APPEND
        )
        first_flush = False
        loop = asyncio.get_event_loop()
        job_config = bigquery.LoadJobConfig(
            write_disposition=disposition,
            autodetect=True,
        )
        await loop.run_in_executor(
            None,
            lambda: bq.load_table_from_json(messages, messages_table, job_config=job_config).result(),
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
        _, users = await extractor.extract_all(on_channel_done=flush_channel)
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
