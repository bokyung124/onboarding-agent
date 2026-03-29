"""FastAPI 앱 엔트리포인트."""

from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google import genai
from google.cloud import bigquery

from app.cache import SearchCache
from app.config import Settings
from app.routers import categories, health, search
from app.services.embedder import EmbedderService
from app.services.llm import LLMService
from app.services.search_orchestrator import SearchOrchestrator
from app.services.vector_search import VectorSearchService


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
    orchestrator = SearchOrchestrator(embedder, vector_search, llm)
    cache = SearchCache(maxsize=settings.cache_max_size, ttl=settings.cache_ttl_seconds)

    # app.state에 주입
    app.state.orchestrator = orchestrator
    app.state.cache = cache

    # Slack Bot (토큰 설정 시에만 시작)
    slack_bot = None
    if settings.slack_bot_token and settings.slack_app_token:
        from app.services.slack_bot import SlackBotService

        slack_bot = SlackBotService(
            bot_token=settings.slack_bot_token,
            app_token=settings.slack_app_token,
            orchestrator=orchestrator,
            cache=cache,
        )
        await slack_bot.start()

    yield

    if slack_bot:
        await slack_bot.stop()
    bq_client.close()


app = FastAPI(
    title="온보딩 에이전트",
    description="노션 데이터 기반 사내 온보딩 에이전트 API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(categories.router)
app.include_router(search.router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {type(exc).__name__}"},
    )
