"""Notion 데이터를 추출하여 BigQuery에 적재하는 스크립트."""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from google.cloud import bigquery

from pipeline.extract.notion_extractor import NotionExtractor

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


async def main() -> None:
    api_key = os.getenv("NOTION_API_KEY")
    root_page_id = os.getenv("NOTION_ROOT_PAGE_ID") or None
    project_id = os.getenv("GCP_PROJECT_ID")
    dataset = os.getenv("BQ_DATASET", "onboarding_agent")

    # 1. Notion 추출
    logging.info("Extracting from Notion...")
    extractor = NotionExtractor(api_key=api_key, root_page_id=root_page_id)
    try:
        pages, blocks, databases, comments = await extractor.crawl_all()
    finally:
        await extractor.close()

    logging.info(
        f"Extracted: {len(pages)} pages, {len(blocks)} blocks, "
        f"{len(databases)} databases, {len(comments)} comments"
    )

    if not pages:
        logging.error("No pages extracted!")
        return

    # 2. BigQuery 적재
    bq = bigquery.Client(project=project_id)

    for p in pages:
        if isinstance(p.get("properties_json"), dict):
            p["properties_json"] = json.dumps(p["properties_json"], ensure_ascii=False)

    for db in databases:
        if isinstance(db.get("schema_json"), dict):
            db["schema_json"] = json.dumps(db["schema_json"], ensure_ascii=False) or "{}"

    for table_name, data in [
        ("raw_notion_pages", pages),
        ("raw_notion_blocks", blocks),
        ("raw_notion_databases", databases),
        ("raw_notion_comments", comments),
    ]:
        if not data:
            logging.error(f"  {table_name}: no data, skipping")
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
        logging.info(f"  {table_name}: {len(data)} rows loaded")

    logging.info("Done!")


if __name__ == "__main__":
    asyncio.run(main())
