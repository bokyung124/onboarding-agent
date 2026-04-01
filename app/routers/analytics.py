"""검색 분석 엔드포인트."""

import asyncio
from functools import partial

from fastapi import APIRouter, Request
from google.cloud import bigquery
from pydantic import BaseModel, Field

router = APIRouter(prefix="/analytics", tags=["analytics"])


class QueryStat(BaseModel):
    query: str
    category: str
    count: int
    avg_latency_ms: int


class DailyVolume(BaseModel):
    date: str
    count: int


class CategoryStat(BaseModel):
    category: str
    count: int
    avg_latency_ms: int
    avg_chunks: float


class TopQueriesResponse(BaseModel):
    queries: list[QueryStat]


class FailedQueriesResponse(BaseModel):
    queries: list[QueryStat]


class DailyVolumeResponse(BaseModel):
    volumes: list[DailyVolume]


class CategoryStatsResponse(BaseModel):
    categories: list[CategoryStat]


def _run_query(bq_client: bigquery.Client, sql: str) -> list[dict]:
    job = bq_client.query(sql)
    return [dict(row) for row in job.result()]


@router.get("/top-queries", response_model=TopQueriesResponse)
async def top_queries(request: Request, days: int = Field(default=7, ge=1, le=90)):
    """최근 N일간 빈도순 상위 50개 쿼리."""
    settings = request.app.state.settings
    table = f"{settings.gcp_project_id}.{settings.bq_dataset}.analytics_search_logs"
    sql = f"""
    SELECT query, category, COUNT(*) as count,
           CAST(AVG(latency_ms) AS INT64) as avg_latency_ms
    FROM `{table}`
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY query, category
    ORDER BY count DESC
    LIMIT 50
    """
    bq_client = bigquery.Client(project=settings.gcp_project_id)
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, partial(_run_query, bq_client, sql))
    bq_client.close()
    return TopQueriesResponse(queries=[QueryStat(**r) for r in rows])


@router.get("/failed-queries", response_model=FailedQueriesResponse)
async def failed_queries(request: Request, days: int = Field(default=7, ge=1, le=90)):
    """최근 N일간 실패(청크 0개 또는 success=false) 쿼리."""
    settings = request.app.state.settings
    table = f"{settings.gcp_project_id}.{settings.bq_dataset}.analytics_search_logs"
    sql = f"""
    SELECT query, category, COUNT(*) as count,
           CAST(AVG(latency_ms) AS INT64) as avg_latency_ms
    FROM `{table}`
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      AND (success = FALSE OR chunks_retrieved = 0)
    GROUP BY query, category
    ORDER BY count DESC
    LIMIT 50
    """
    bq_client = bigquery.Client(project=settings.gcp_project_id)
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, partial(_run_query, bq_client, sql))
    bq_client.close()
    return FailedQueriesResponse(queries=[QueryStat(**r) for r in rows])


@router.get("/daily-volume", response_model=DailyVolumeResponse)
async def daily_volume(request: Request, days: int = Field(default=30, ge=1, le=90)):
    """최근 N일간 일별 검색 건수."""
    settings = request.app.state.settings
    table = f"{settings.gcp_project_id}.{settings.bq_dataset}.analytics_search_logs"
    sql = f"""
    SELECT CAST(DATE(timestamp) AS STRING) as date, COUNT(*) as count
    FROM `{table}`
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date
    ORDER BY date DESC
    """
    bq_client = bigquery.Client(project=settings.gcp_project_id)
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, partial(_run_query, bq_client, sql))
    bq_client.close()
    return DailyVolumeResponse(volumes=[DailyVolume(**r) for r in rows])


@router.get("/category-stats", response_model=CategoryStatsResponse)
async def category_stats(request: Request, days: int = Field(default=7, ge=1, le=90)):
    """최근 N일간 카테고리별 검색 통계."""
    settings = request.app.state.settings
    table = f"{settings.gcp_project_id}.{settings.bq_dataset}.analytics_search_logs"
    sql = f"""
    SELECT category, COUNT(*) as count,
           CAST(AVG(latency_ms) AS INT64) as avg_latency_ms,
           ROUND(AVG(chunks_retrieved), 1) as avg_chunks
    FROM `{table}`
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY category
    ORDER BY count DESC
    """
    bq_client = bigquery.Client(project=settings.gcp_project_id)
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, partial(_run_query, bq_client, sql))
    bq_client.close()
    return CategoryStatsResponse(categories=[CategoryStat(**r) for r in rows])
