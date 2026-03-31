"""Discovery Engine Ranking API를 사용해 검색 결과를 재정렬한다."""

import asyncio
import logging
from functools import partial

from google.cloud import discoveryengine_v1 as discoveryengine

from app.models.domain import ChunkResult

logger = logging.getLogger(__name__)

RANKING_MODEL = "semantic-ranker-default@latest"


class RerankerService:
    def __init__(self, project_id: str):
        self._client = discoveryengine.RankServiceClient()
        self._ranking_config = (
            f"projects/{project_id}/locations/global/rankingConfigs/default_ranking_config"
        )

    async def rerank(
        self, query: str, chunks: list[ChunkResult], top_n: int = 8
    ) -> list[ChunkResult]:
        """Discovery Engine Ranking API로 청크를 재정렬하여 top_n개를 반환한다."""
        if not chunks:
            return chunks
        top_n = min(top_n, len(chunks))

        records = [
            discoveryengine.RankingRecord(
                id=str(i),
                title=chunk.page_title or "",
                content=chunk.content,
            )
            for i, chunk in enumerate(chunks)
        ]

        rank_request = discoveryengine.RankRequest(
            ranking_config=self._ranking_config,
            model=RANKING_MODEL,
            query=query,
            records=records,
            top_n=top_n,
        )

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, partial(self._client.rank, request=rank_request)
        )

        # response.records는 score 내림차순으로 정렬되어 반환됨
        return [chunks[int(record.id)] for record in response.records]
