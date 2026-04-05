"""검색 플로우를 오케스트레이션한다: 임베딩 → 벡터 검색 → LLM 답변 생성."""

import asyncio
import logging
import time
from functools import partial

from app.cache import ChecklistCache, SearchCache
from app.models.categories import ONBOARDING_CATEGORY_NAMES
from app.models.domain import ChunkResult
from app.models.request import SearchRequest
from app.models.response import (
    ChecklistResponse,
    ChecklistStep,
    SearchMetadata,
    SearchResponse,
    Source,
)
from app.services.analytics import SearchAnalytics
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
        checklist_cache: ChecklistCache | None = None,
        analytics: SearchAnalytics | None = None,
    ):
        self._embedder = embedder
        self._vector_search = vector_search
        self._llm = llm
        self._reranker = reranker
        self._cache = cache
        self._checklist_cache = checklist_cache
        self._analytics = analytics

    async def search(
        self,
        request: SearchRequest,
        *,
        is_onboarding: bool = False,
        conversation_history: list | None = None,
        user_id: str | None = None,
    ) -> SearchResponse:
        """사용자 검색 요청을 처리하여 답변과 출처를 반환한다."""
        if self._cache and not conversation_history:
            cached = self._cache.get(request)
            if cached:
                logger.info("response cache=hit")
                return cached

        start = time.monotonic()

        # 1. 쿼리 임베딩 (동기 API → executor)
        t0 = time.monotonic()
        loop = asyncio.get_running_loop()
        embedding = await loop.run_in_executor(
            None, partial(self._embedder.embed_query, request.query)
        )
        t1 = time.monotonic()
        logger.info("step=embed elapsed=%.1fs", t1 - t0)

        # 2. 벡터 검색
        chunks = await self._vector_search.search(
            embedding,
            request.category,
            client_name=request.client_name,
            tags=request.tags,
            is_onboarding=is_onboarding,
        )

        # 2-a. Fallback: is_onboarding=True에서 0건이면 is_onboarding=False로 재검색
        if not chunks and is_onboarding:
            logger.warning(
                "search fallback: 0 chunks with is_onboarding=True, "
                "retrying without onboarding filter. category=%s",
                request.category,
            )
            chunks = await self._vector_search.search(
                embedding,
                request.category,
                client_name=request.client_name,
                tags=request.tags,
                is_onboarding=False,
            )

        t2 = time.monotonic()
        logger.info("step=vector_search elapsed=%.1fs chunks=%d", t2 - t1, len(chunks))

        # 2-b. Cross-encoder reranking (설정된 경우)
        if self._reranker:
            chunks = await self._reranker.rerank(
                request.query, chunks, top_n=self._vector_search.result_limit
            )
            t2b = time.monotonic()
            logger.info("step=rerank elapsed=%.1fs", t2b - t2)

        # 2-c. LLM 입력 전 같은 page_id 청크 중복 제거 (best-ranked 유지)
        seen_pages: set[str] = set()
        deduped: list[ChunkResult] = []
        for chunk in chunks:
            key = f"{chunk.source_type}:{chunk.page_id}"
            if key not in seen_pages:
                seen_pages.add(key)
                deduped.append(chunk)
        chunks = deduped

        # 3. LLM 답변 생성 (cited_indices: 실제 인용한 출처 번호 목록, follow_ups: 후속 질문)
        t3 = time.monotonic()
        answer, cited_indices, follow_ups = await self._llm.generate_answer(
            request.query,
            request.category,
            chunks,
            is_onboarding=is_onboarding,
            conversation_history=conversation_history,
        )
        t4 = time.monotonic()
        logger.info("step=llm elapsed=%.1fs", t4 - t3)

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
            follow_up_questions=follow_ups,
        )

        if self._cache and not conversation_history:
            self._cache.set(request, response)
            logger.info("response cache=miss sources=%d", len(response.sources))

        if self._analytics:
            asyncio.create_task(
                self._analytics.log_search(
                    query=request.query,
                    category=request.category,
                    chunks_retrieved=len(chunks),
                    sources_count=len(sources),
                    latency_ms=elapsed_ms,
                    is_onboarding=is_onboarding,
                    user_id=user_id,
                    client_name=request.client_name,
                    tags=request.tags,
                    answer=response.answer,
                )
            )

        return response

    async def multi_step_search(
        self,
        request: SearchRequest,
        *,
        is_onboarding: bool = False,
        conversation_history: list | None = None,
        user_id: str | None = None,
    ) -> SearchResponse:
        """복잡한 질문을 분해하여 여러 검색을 수행하고 종합 답변을 생성한다."""
        sub_queries = await self._llm.decompose_query(request.query)

        if len(sub_queries) <= 1:
            return await self.search(
                request,
                is_onboarding=is_onboarding,
                conversation_history=conversation_history,
                user_id=user_id,
            )

        start = time.monotonic()
        logger.info("multi_step sub_queries=%d queries=%r", len(sub_queries), sub_queries)

        loop = asyncio.get_running_loop()
        all_chunks: list[ChunkResult] = []
        for sq in sub_queries:
            embedding = await loop.run_in_executor(None, partial(self._embedder.embed_query, sq))
            chunks = await self._vector_search.search(
                embedding,
                request.category,
                client_name=request.client_name,
                tags=request.tags,
                is_onboarding=is_onboarding,
            )
            all_chunks.extend(chunks)

        # Fallback: 전체 결과가 0건이면 is_onboarding 제거 후 재검색
        if not all_chunks and is_onboarding:
            logger.warning(
                "multi_step fallback: 0 chunks with is_onboarding=True, "
                "retrying without onboarding filter. category=%s",
                request.category,
            )
            for sq in sub_queries:
                embedding = await loop.run_in_executor(
                    None, partial(self._embedder.embed_query, sq)
                )
                chunks = await self._vector_search.search(
                    embedding,
                    request.category,
                    client_name=request.client_name,
                    tags=request.tags,
                    is_onboarding=False,
                )
                all_chunks.extend(chunks)

        # 중복 제거 (chunk_id 기준, 최초 출현 유지)
        seen_ids: set[str] = set()
        deduped: list[ChunkResult] = []
        for chunk in all_chunks:
            if chunk.chunk_id not in seen_ids:
                seen_ids.add(chunk.chunk_id)
                deduped.append(chunk)

        # 페이지 단위 중복 제거
        seen_pages: set[str] = set()
        page_deduped: list[ChunkResult] = []
        for chunk in deduped:
            key = f"{chunk.source_type}:{chunk.page_id}"
            if key not in seen_pages:
                seen_pages.add(key)
                page_deduped.append(chunk)
        chunks = page_deduped

        # Reranking
        if self._reranker:
            chunks = await self._reranker.rerank(
                request.query, chunks, top_n=self._vector_search.result_limit
            )

        answer, cited_indices, follow_ups = await self._llm.generate_answer(
            request.query,
            request.category,
            chunks,
            is_onboarding=is_onboarding,
            conversation_history=conversation_history,
        )

        if cited_indices:
            cited_chunks = [chunks[i - 1] for i in cited_indices if 1 <= i <= len(chunks)]
        else:
            cited_chunks = chunks[:3]
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
            follow_up_questions=follow_ups,
        )

        if self._analytics:
            asyncio.create_task(
                self._analytics.log_search(
                    query=request.query,
                    category=request.category,
                    chunks_retrieved=len(chunks),
                    sources_count=len(sources),
                    latency_ms=elapsed_ms,
                    is_onboarding=is_onboarding,
                    user_id=user_id,
                    client_name=request.client_name,
                    tags=request.tags,
                    answer=response.answer,
                )
            )

        return response

    async def generate_checklist(self, category: str) -> ChecklistResponse:
        """카테고리별 온보딩 체크리스트를 생성한다."""
        if self._checklist_cache:
            cached = self._checklist_cache.get(category)
            if cached:
                logger.info("checklist cache=hit category=%s", category)
                return cached

        start = time.monotonic()
        cat_name = ONBOARDING_CATEGORY_NAMES.get(category, category)

        # 1. 합성 쿼리 임베딩
        loop = asyncio.get_running_loop()
        embedding = await loop.run_in_executor(
            None, partial(self._embedder.embed_query, f"{cat_name} 온보딩 전체 가이드")
        )

        # 2. 벡터 검색 (넓은 범위)
        chunks = await self._vector_search.search(
            embedding,
            category,
            is_onboarding=True,
            top_k=80,
            result_limit=15,
        )

        # 2-b. Fallback: is_onboarding 제거 후 재검색
        if not chunks:
            logger.warning(
                "checklist fallback: 0 chunks with is_onboarding=True, "
                "retrying without onboarding filter. category=%s",
                category,
            )
            chunks = await self._vector_search.search(
                embedding,
                category,
                is_onboarding=False,
                top_k=80,
                result_limit=15,
            )

        # 2-c. Fallback: 카테고리도 제거 후 재검색
        if not chunks:
            logger.warning(
                "checklist fallback: 0 chunks with category=%s, retrying with category=all",
                category,
            )
            chunks = await self._vector_search.search(
                embedding,
                "all",
                is_onboarding=False,
                top_k=80,
                result_limit=15,
            )

        # 3. 페이지 중복 제거
        seen_pages: set[str] = set()
        deduped: list[ChunkResult] = []
        for chunk in chunks:
            key = f"{chunk.source_type}:{chunk.page_id}"
            if key not in seen_pages:
                seen_pages.add(key)
                deduped.append(chunk)
        chunks = deduped

        # 4. LLM 체크리스트 생성
        title, steps_data = await self._llm.generate_checklist(category, chunks)

        # 5. 응답 구성
        sources = self._deduplicate_sources(chunks)
        steps = [ChecklistStep(**s) for s in steps_data]
        elapsed_ms = int((time.monotonic() - start) * 1000)

        response = ChecklistResponse(
            category=category,
            category_name=cat_name,
            title=title,
            steps=steps,
            sources=sources,
            metadata=SearchMetadata(
                chunks_retrieved=len(chunks),
                latency_ms=elapsed_ms,
            ),
        )

        if self._checklist_cache:
            self._checklist_cache.set(category, response)
            logger.info("checklist cache=miss category=%s steps=%d", category, len(steps))

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
                    client_name=chunk.client_name,
                    tags=chunk.tags,
                )
            )
        return sources
