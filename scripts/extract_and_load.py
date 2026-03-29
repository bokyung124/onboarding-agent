"""Notion 데이터를 추출하여 BigQuery에 적재하는 스크립트.

환경변수:
    EXTRACT_MODE: "full" (기본, WRITE_TRUNCATE) | "incremental" (WRITE_APPEND, since 사용)
"""

import asyncio
import logging
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

# 콘솔 + 파일 동시 로깅
_log_file = Path(__file__).resolve().parent.parent / "extract.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_log_file, mode="w", encoding="utf-8"),
    ],
)


def get_checkpoint(project_id: str, dataset: str) -> str | None:
    """BigQuery에서 마지막 추출 시점을 조회한다."""
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    query = f"""
    SELECT MAX(_extracted_at) as last_extracted
    FROM `{project_id}.{dataset}.raw_notion_pages`
    """
    try:
        result = list(client.query(query).result())
        if result and result[0].last_extracted:
            checkpoint = result[0].last_extracted - timedelta(minutes=5)
            checkpoint_str = checkpoint.isoformat()
            logging.info("Checkpoint: %s", checkpoint_str)
            return checkpoint_str
    except Exception:
        logging.info("No checkpoint found, performing full extraction")
    finally:
        client.close()
    return None


async def main() -> None:
    api_key = os.getenv("NOTION_API_KEY")
    root_page_id = os.getenv("NOTION_ROOT_PAGE_ID") or None
    project_id = os.getenv("GCP_PROJECT_ID")
    dataset = os.getenv("BQ_DATASET", "onboarding_agent")
    mode = os.getenv("EXTRACT_MODE", "full")

    from pipeline.extract.bigquery_sink import BigQueryBatchSink
    from pipeline.extract.notion_extractor import NotionExtractor

    # 증분 모드: checkpoint 조회
    since: str | None = None
    if mode == "incremental":
        since = get_checkpoint(project_id, dataset)
        logging.info("Incremental mode: since=%s", since)
    else:
        logging.info("Full mode: WRITE_TRUNCATE")

    write_disposition = "WRITE_TRUNCATE" if mode == "full" else "WRITE_APPEND"

    sink = BigQueryBatchSink(
        project_id=project_id,
        dataset=dataset,
        write_disposition=write_disposition,
    )

    extractor = NotionExtractor(api_key=api_key, root_page_id=root_page_id)
    try:
        await extractor.crawl_all(since=since, sink=sink, batch_size=100)
    finally:
        await extractor.close()
        sink.close()

    logging.info(
        "Done! Total: %d pages, %d blocks, %d databases, %d comments",
        sink.total_pages,
        sink.total_blocks,
        sink.total_databases,
        sink.total_comments,
    )


if __name__ == "__main__":
    asyncio.run(main())
