"""mart_notion_chunks에서 변경된 청크를 감지하고 Gemini 임베딩을 생성하여 BigQuery에 적재한다."""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from google import genai
from google.cloud import bigquery

from pipeline.embed.generate_embeddings import (
    detect_changed_chunks,
    generate_embeddings,
    load_vectors_to_bigquery,
)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    project_id = os.getenv("GCP_PROJECT_ID")
    dataset = os.getenv("BQ_DATASET", "onboarding_agent")
    bq_client = bigquery.Client(project=project_id)
    genai_client = genai.Client(
        api_key=os.getenv("GEMINI_API_KEY"),
    )

    # 1. 변경된 청크 감지
    logging.info("Detecting changed chunks...")
    chunks = detect_changed_chunks(bq_client, project_id, dataset)

    if not chunks:
        logging.info("No changed chunks. Done!")
        return

    logging.info("Found %d chunks to embed", len(chunks))

    # 2. 임베딩 생성
    logging.info("Generating embeddings...")
    vectors = generate_embeddings(genai_client, chunks)
    logging.info("Generated %d vectors", len(vectors))

    # 3. BigQuery 적재 (MERGE upsert)
    logging.info("Loading vectors to BigQuery...")
    load_vectors_to_bigquery(bq_client, project_id, dataset, vectors)

    logging.info("Done! %d vectors loaded", len(vectors))


if __name__ == "__main__":
    main()
