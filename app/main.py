"""FastAPI 앱 엔트리포인트."""

import asyncio
import logging
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google import genai
from google.cloud import bigquery

from app.cache import ChecklistCache, ConversationCache, SearchCache
from app.config import Settings
from app.routers import analytics as analytics_router
from app.routers import categories, dashboard, health, onboarding, search
from app.services.analytics import SearchAnalytics
from app.services.embedder import EmbedderService
from app.services.llm import LLMService
from app.services.reranker import RerankerService
from app.services.search_orchestrator import SearchOrchestrator
from app.services.vector_search import VectorSearchService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@lru_cache
def get_settings() -> Settings:
    return Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # 클라이언트 초기화
    bq_client = bigquery.Client(project=settings.gcp_project_id)
    genai_client = genai.Client(api_key=settings.gemini_api_key)

    # 서비스 생성
    embedder = EmbedderService(genai_client, model=settings.gemini_embedding_model)
    vector_search = VectorSearchService(bq_client, settings)
    llm = LLMService(genai_client, model=settings.gemini_model)
    reranker = (
        RerankerService(project_id=settings.gcp_project_id) if settings.reranker_enabled else None
    )
    logging.getLogger(__name__).info(
        "reranker_enabled=%s reranker=%s",
        settings.reranker_enabled,
        "ON" if reranker else "OFF",
    )
    cache = SearchCache(maxsize=settings.cache_max_size, ttl=settings.cache_ttl_seconds)
    checklist_cache = ChecklistCache(
        maxsize=settings.checklist_cache_max_size,
        ttl=settings.checklist_cache_ttl_seconds,
    )
    conversation_cache = ConversationCache(
        maxsize=settings.conversation_cache_max_size,
        ttl=settings.conversation_cache_ttl_seconds,
        max_turns=settings.conversation_max_turns,
    )
    analytics = SearchAnalytics(
        bq_client=bq_client,
        project_id=settings.gcp_project_id,
        dataset=settings.bq_dataset,
    )
    # 테이블 생성은 백그라운드에서 (startup 블로킹 방지)
    asyncio.create_task(analytics.ensure_table())

    orchestrator = SearchOrchestrator(
        embedder,
        vector_search,
        llm,
        reranker=reranker,
        cache=cache,
        checklist_cache=checklist_cache,
        analytics=analytics,
        settings=settings,
    )

    # app.state에 주입
    app.state.orchestrator = orchestrator
    app.state.cache = cache
    app.state.checklist_cache = checklist_cache
    app.state.conversation_cache = conversation_cache
    app.state.settings = settings

    # Slack Bot (토큰 설정 시에만 시작)
    slack_bot = None
    if settings.slack_bot_token and settings.slack_app_token:
        from app.services.slack_bot import SlackBotService

        slack_bot = SlackBotService(
            bot_token=settings.slack_bot_token,
            app_token=settings.slack_app_token,
            orchestrator=orchestrator,
            search_timeout=settings.slack_search_timeout_seconds,
            conversation_cache=conversation_cache,
        )
        asyncio.create_task(slack_bot.start())

    yield

    await analytics.flush()
    if slack_bot:
        await slack_bot.stop()
    bq_client.close()


app = FastAPI(
    title="온보딩 에이전트",
    description="노션, 슬랙 데이터 기반 사내 온보딩 에이전트 API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(categories.router)
app.include_router(search.router)
app.include_router(onboarding.router)
app.include_router(analytics_router.router)
app.include_router(dashboard.router)


@app.get("/")
async def root():
    return {"service": "온보딩 에이전트", "health": "/health", "docs": "/docs"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logging.getLogger(__name__).exception("Unhandled exception: %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {type(exc).__name__}"},
    )
