"""신규 Slack 채널의 전체 히스토리를 BigQuery에 적재한다.

기존 채널 데이터에 영향을 주지 않고, 지정한 채널의 과거 메시지를 전량 수집한다.

사용법:
    # 프로젝트 루트에서 실행
    python scripts/backfill_slack_channels.py --channels C0NEWCHAN1,C0NEWCHAN2
    python scripts/backfill_slack_channels.py --channels C0NEWCHAN1 --since 2025-01-01
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

from google.cloud import bigquery

from pipeline.extract.slack_extractor import SlackExtractor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="신규 Slack 채널 전체 히스토리 적재")
    parser.add_argument(
        "--channels",
        required=True,
        help="수집할 채널 ID (쉼표 구분). 예: C0NEWCHAN1,C0NEWCHAN2",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="수집 시작일 (YYYY-MM-DD). 미지정 시 채널 전체 히스토리 수집.",
    )
    return parser.parse_args()


def _to_unix_ts(date_str: str) -> str:
    """YYYY-MM-DD 문자열을 Unix timestamp 문자열로 변환한다."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return str(dt.timestamp())


def _load_to_bigquery(
    bq_client: bigquery.Client,
    project_id: str,
    dataset: str,
    messages: list[dict],
    users: list[dict],
) -> None:
    table_mapping = {
        "messages": (f"{project_id}.{dataset}.raw_slack_messages", messages),
        "users": (f"{project_id}.{dataset}.raw_slack_users", users),
    }

    for key, (table_id, records) in table_mapping.items():
        if not records:
            logger.info("No %s to load", key)
            continue

        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            autodetect=True,
        )
        job = bq_client.load_table_from_json(records, table_id, job_config=job_config)
        job.result()
        logger.info("Loaded %d %s to %s", len(records), key, table_id)


async def backfill(channel_ids: list[str], since_ts: str | None) -> None:
    bot_token = os.environ["SLACK_BOT_TOKEN"]
    workspace = os.environ.get("SLACK_WORKSPACE", "")
    project_id = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ.get("BQ_DATASET", "onboarding_agent")

    logger.info("Backfill 시작: 채널 %s / since_ts=%s", channel_ids, since_ts)

    extractor = SlackExtractor(
        bot_token=bot_token,
        channel_ids=channel_ids,
        workspace=workspace,
    )

    bq_client = bigquery.Client(project=project_id)

    try:
        messages, users = await extractor.extract_all(since_ts=since_ts)
    finally:
        await extractor.close()

    logger.info("수집 완료: 메시지 %d건, 유저 %d명", len(messages), len(users))

    _load_to_bigquery(bq_client, project_id, dataset, messages, users)
    logger.info("BigQuery 적재 완료")


def main() -> None:
    args = _parse_args()
    channel_ids = [c.strip() for c in args.channels.split(",") if c.strip()]

    if not channel_ids:
        logger.error("채널 ID를 지정하세요")
        sys.exit(1)

    since_ts = _to_unix_ts(args.since) if args.since else None

    asyncio.run(backfill(channel_ids, since_ts))


if __name__ == "__main__":
    main()
