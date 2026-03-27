"""검색 플로우를 오케스트레이션한다: 임베딩 → 벡터 검색 → LLM 답변 생성."""

import asyncio
import time
from functools import partial

from app.models.domain import ChunkResult
from app.models.request import SearchRequest
from app.models.response import SearchMetadata, SearchResponse, Source
from app.services.embedder import EmbedderService
from app.services.llm import LLMService
from app.services.vector_search import VectorSearchService


class SearchOrchestrator:
    def __init__(
        self,
        embedder: EmbedderService,
        vector_search: VectorSearchService,
        llm: LLMService,
    ):
        self._embedder = embedder
        self._vector_search = vector_search
        self._llm = llm

    async def search(self, request: SearchRequest) -> SearchResponse:
        """사용자 검색 요청을 처리하여 답변과 출처를 반환한다."""
        start = time.monotonic()

        # 1. 쿼리 임베딩 (동기 API → executor)
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(
            None, partial(self._embedder.embed_query, request.query)
        )

        # 2. 벡터 검색
        chunks = await self._vector_search.search(embedding, request.category)

        # 3. LLM 답변 생성
        answer = await self._llm.generate_answer(
            request.query, request.category, chunks
        )

        # 4. 출처 조합 (중복 페이지 제거)
        sources = self._deduplicate_sources(chunks)

        elapsed_ms = int((time.monotonic() - start) * 1000)

        return SearchResponse(
            answer=answer,
            sources=sources,
            category=request.category,
            metadata=SearchMetadata(
                chunks_retrieved=len(chunks),
                latency_ms=elapsed_ms,
            ),
        )

    def _deduplicate_sources(self, chunks: list[ChunkResult]) -> list[Source]:
        """같은 출처의 중복을 제거한다."""
        seen: set[str] = set()
        sources: list[Source] = []
        for chunk in chunks:
            key = f"{chunk.source_type}:{chunk.page_id}"
            if key in seen:
                continue
            seen.add(key)
            sources.append(
                Source(
                    title=chunk.page_title,
                    url=chunk.source_url,
                    breadcrumb=chunk.breadcrumb,
                    page_id=chunk.page_id,
                    source_type=chunk.source_type,
                )
            )
        return sources
