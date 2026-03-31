"""검색 플로우를 오케스트레이션한다: 임베딩 → 벡터 검색 → LLM 답변 생성."""

import asyncio
import logging
import time
from functools import partial

from app.cache import SearchCache
from app.models.domain import ChunkResult
from app.models.request import SearchRequest
from app.models.response import SearchMetadata, SearchResponse, Source
from app.services.embedder import EmbedderService
from app.services.llm import LLMService
from app.services.reranker import RerankerService
from app.services.vector_search import VectorSearchService

logger = logging.getLogger(__name__)


class SearchOrchestrator:
    def __init__(
        self,
        embedder: EmbedderService,
        vector_search: VectorSearchService,
        llm: LLMService,
        reranker: RerankerService | None = None,
        cache: SearchCache | None = None,
    ):
        self._embedder = embedder
        self._vector_search = vector_search
        self._llm = llm
        self._reranker = reranker
        self._cache = cache

    async def search(self, request: SearchRequest) -> SearchResponse:
        """사용자 검색 요청을 처리하여 답변과 출처를 반환한다."""
        if self._cache:
            cached = self._cache.get(request)
            if cached:
                logger.info("response cache=hit")
                return cached

        start = time.monotonic()

        # 1. 쿼리 임베딩 (동기 API → executor)
        loop = asyncio.get_running_loop()
        embedding = await loop.run_in_executor(
            None, partial(self._embedder.embed_query, request.query)
        )

        # 2. 벡터 검색
        chunks = await self._vector_search.search(
            embedding,
            request.category,
            client_name=request.client_name,
            tags=request.tags,
        )

        # 2-b. Cross-encoder reranking (설정된 경우)
        if self._reranker:
            chunks = await self._reranker.rerank(
                request.query, chunks, top_n=self._vector_search.result_limit
            )

        # 2-c. 상위 3개 Notion 청크에 부모 페이지 본문 주입 (parent-child chunking)
        chunks = await self._vector_search.enrich_with_parent_context(chunks, top_n=3)

        # 2-d. LLM 입력 전 같은 page_id 청크 중복 제거 (best-ranked 유지)
        seen_pages: set[str] = set()
        deduped: list[ChunkResult] = []
        for chunk in chunks:
            key = f"{chunk.source_type}:{chunk.page_id}"
            if key not in seen_pages:
                seen_pages.add(key)
                deduped.append(chunk)
        chunks = deduped

        # 3. LLM 답변 생성 (cited_indices: 실제 인용한 출처 번호 목록)
        answer, cited_indices = await self._llm.generate_answer(
            request.query, request.category, chunks
        )

        # 4. 실제 인용된 청크만 sources에 포함 (cited_indices 기반)
        if cited_indices:
            cited_chunks = [chunks[i - 1] for i in cited_indices if 1 <= i <= len(chunks)]
        else:
            cited_chunks = chunks[:3]  # fallback: 상위 3개만 노출
        sources = self._deduplicate_sources(cited_chunks)

        elapsed_ms = int((time.monotonic() - start) * 1000)

        response = SearchResponse(
            answer=answer,
            sources=sources,
            category=request.category,
            metadata=SearchMetadata(
                chunks_retrieved=len(chunks),
                latency_ms=elapsed_ms,
            ),
        )

        if self._cache:
            self._cache.set(request, response)
            logger.info("response cache=miss sources=%d", len(response.sources))

        return response

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
