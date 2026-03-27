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

    # 1. Slack 추출
    logging.info("Extracting from Slack...")
    extractor = SlackExtractor(
        bot_token=bot_token,
        channel_ids=channel_ids,
        workspace=workspace,
    )
    try:
        messages, users = await extractor.extract_all()
    finally:
        await extractor.close()

    logging.info("Extracted: %d messages, %d users", len(messages), len(users))

    if not messages:
        logging.warning("No messages extracted!")
        return

    # 2. BigQuery 적재
    bq = bigquery.Client(project=project_id)

    for table_name, data in [
        ("raw_slack_messages", messages),
        ("raw_slack_users", users),
    ]:
        if not data:
            logging.warning("  %s: no data, skipping", table_name)
            continue
        table_ref = f"{project_id}.{dataset}.{table_name}"
        job = bq.load_table_from_json(
            data,
            table_ref,
            job_config=bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                autodetect=True,
            ),
        )
        job.result()
        logging.info("  %s: %d rows loaded", table_name, len(data))

    logging.info("Done!")


if __name__ == "__main__":
    asyncio.run(main())
