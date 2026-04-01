"""mart_enterprise_vectors 테이블에 IVF 벡터 인덱스를 생성한다.

인덱스가 이미 존재하면 건너뛴다. 수동 실행 또는 파이프라인에서 호출한다.
"""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from google.cloud import bigquery

from pipeline.embed.generate_embeddings import ensure_vector_index

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    project_id = os.getenv("GCP_PROJECT_ID")
    dataset = os.getenv("BQ_DATASET", "onboarding_agent")
    bq_client = bigquery.Client(project=project_id)

    ensure_vector_index(bq_client, project_id, dataset)
    logging.info("Vector index creation completed")


if __name__ == "__main__":
    main()
