"""사용자별 사용량 대시보드 엔드포인트."""

import asyncio
import hashlib
import hmac
import logging
import secrets
from functools import partial
from pathlib import Path

from cachetools import TTLCache
from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from google.cloud import bigquery
from pydantic import BaseModel
from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

_user_name_cache: TTLCache[str, str] = TTLCache(maxsize=500, ttl=3600)


class UserStat(BaseModel):
    user_id: str
    display_name: str
    query_count: int
    last_active: str
    first_seen: str
    avg_latency_ms: int


class HistoryEntry(BaseModel):
    search_id: str
    timestamp: str
    query: str
    answer: str | None
    category: str
    latency_ms: int
    success: bool
    sources_count: int


class UserListResponse(BaseModel):
    users: list[UserStat]


class UserHistoryResponse(BaseModel):
    entries: list[HistoryEntry]


def _run_query(bq_client: bigquery.Client, sql: str) -> list[dict]:
    job = bq_client.query(sql)
    return [dict(row) for row in job.result()]


def _run_parameterized_query(
    bq_client: bigquery.Client,
    sql: str,
    params: list[bigquery.ScalarQueryParameter],
) -> list[dict]:
    config = bigquery.QueryJobConfig(query_parameters=params)
    job = bq_client.query(sql, job_config=config)
    return [dict(row) for row in job.result()]


async def _resolve_user_names(user_ids: list[str], bot_token: str) -> dict[str, str]:
    """Slack user_id를 display name으로 변환한다 (캐시 활용)."""
    result: dict[str, str] = {}
    to_fetch: list[str] = []

    for uid in user_ids:
        if uid in _user_name_cache:
            result[uid] = _user_name_cache[uid]
        else:
            to_fetch.append(uid)

    if to_fetch and bot_token:
        client = AsyncWebClient(token=bot_token)
        for uid in to_fetch:
            try:
                resp = await client.users_info(user=uid)
                profile = resp["user"]["profile"]
                name = profile.get("display_name") or resp["user"].get("real_name", uid)
                _user_name_cache[uid] = name
                result[uid] = name
            except Exception:
                logger.warning("Failed to resolve Slack user %s", uid)
                result[uid] = uid
    else:
        for uid in to_fetch:
            result[uid] = uid

    return result


def _get_table_id(settings) -> str:
    return f"{settings.gcp_project_id}.{settings.bq_dataset}.analytics_search_logs"


# ── Auth ──────────────────────────────────────���─────────────

_TOKEN_SECRET = secrets.token_hex(32)


def _make_token(password: str) -> str:
    """비밀번호 기반 HMAC 토큰을 생성한다."""
    return hmac.new(_TOKEN_SECRET.encode(), password.encode(), hashlib.sha256).hexdigest()


def _check_auth(request: Request) -> bool:
    """쿠키의 인증 토큰이 유효한지 검사한다. 비밀번호 미설정이면 통과."""
    password = request.app.state.settings.dashboard_password
    if not password:
        return True
    token = request.cookies.get("dashboard_token", "")
    return hmac.compare_digest(token, _make_token(password))


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    if _check_auth(request):
        return RedirectResponse("/dashboard/", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": error},
    )


@router.post("/login")
async def login_submit(request: Request, password: str = Form(...)):
    expected = request.app.state.settings.dashboard_password
    if not expected or hmac.compare_digest(password, expected):
        response = RedirectResponse("/dashboard/", status_code=302)
        response.set_cookie(
            "dashboard_token",
            _make_token(expected),
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=86400 * 7,
        )
        return response
    return RedirectResponse("/dashboard/login?error=1", status_code=302)


@router.get("/logout")
async def logout():
    response = RedirectResponse("/dashboard/login", status_code=302)
    response.delete_cookie("dashboard_token")
    return response


# ── JSON API ────────────────────────────────────────────────


@router.get("/api/users", response_model=UserListResponse)
async def api_user_list(request: Request, days: int = Query(default=30, ge=1, le=365)):
    """사용자별 사용량 통계."""
    if not _check_auth(request):
        return RedirectResponse("/dashboard/login", status_code=302)
    settings = request.app.state.settings
    table = _get_table_id(settings)
    sql = f"""
    SELECT IFNULL(user_id, 'anonymous') as user_id,
           COUNT(*) as query_count,
           CAST(MAX(timestamp) AS STRING) as last_active,
           CAST(MIN(timestamp) AS STRING) as first_seen,
           CAST(AVG(latency_ms) AS INT64) as avg_latency_ms
    FROM `{table}`
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY user_id
    ORDER BY query_count DESC
    """
    bq_client = bigquery.Client(project=settings.gcp_project_id)
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, partial(_run_query, bq_client, sql))
    bq_client.close()

    user_ids = [r["user_id"] for r in rows]
    names = await _resolve_user_names(user_ids, settings.slack_bot_token)

    users = [UserStat(display_name=names.get(r["user_id"], r["user_id"]), **r) for r in rows]
    return UserListResponse(users=users)


@router.get("/api/users/{user_id}/history", response_model=UserHistoryResponse)
async def api_user_history(
    request: Request,
    user_id: str,
    days: int = Query(default=30, ge=1, le=365),
):
    """사용자의 Q&A 히스토리."""
    if not _check_auth(request):
        return RedirectResponse("/dashboard/login", status_code=302)
    settings = request.app.state.settings
    table = _get_table_id(settings)
    sql = f"""
    SELECT search_id,
           CAST(timestamp AS STRING) as timestamp,
           query, answer, category,
           latency_ms, success, sources_count
    FROM `{table}`
    WHERE IFNULL(user_id, 'anonymous') = @user_id
      AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    ORDER BY timestamp DESC
    LIMIT 200
    """
    params = [bigquery.ScalarQueryParameter("user_id", "STRING", user_id)]
    bq_client = bigquery.Client(project=settings.gcp_project_id)
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(
        None, partial(_run_parameterized_query, bq_client, sql, params)
    )
    bq_client.close()

    entries = [HistoryEntry(**r) for r in rows]
    return UserHistoryResponse(entries=entries)


# ── HTML Pages ──────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request, days: int = Query(default=30, ge=1, le=365)):
    """사용자 목록 대시보드 페이지."""
    if not _check_auth(request):
        return RedirectResponse("/dashboard/login", status_code=302)
    settings = request.app.state.settings
    table = _get_table_id(settings)
    sql = f"""
    SELECT IFNULL(user_id, 'anonymous') as user_id,
           COUNT(*) as query_count,
           CAST(MAX(timestamp) AS STRING) as last_active,
           CAST(MIN(timestamp) AS STRING) as first_seen,
           CAST(AVG(latency_ms) AS INT64) as avg_latency_ms
    FROM `{table}`
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY user_id
    ORDER BY query_count DESC
    """
    bq_client = bigquery.Client(project=settings.gcp_project_id)
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, partial(_run_query, bq_client, sql))
    bq_client.close()

    user_ids = [r["user_id"] for r in rows]
    names = await _resolve_user_names(user_ids, settings.slack_bot_token)

    users = [{**r, "display_name": names.get(r["user_id"], r["user_id"])} for r in rows]
    total_queries = sum(r["query_count"] for r in rows)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"users": users, "days": days, "total_queries": total_queries},
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail_page(
    request: Request,
    user_id: str,
    days: int = Query(default=30, ge=1, le=365),
):
    """사용자별 Q&A 히스토리 페이지."""
    if not _check_auth(request):
        return RedirectResponse("/dashboard/login", status_code=302)
    settings = request.app.state.settings
    table = _get_table_id(settings)

    sql = f"""
    SELECT search_id,
           CAST(timestamp AS STRING) as timestamp,
           query, answer, category,
           latency_ms, success, sources_count
    FROM `{table}`
    WHERE IFNULL(user_id, 'anonymous') = @user_id
      AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    ORDER BY timestamp DESC
    LIMIT 200
    """
    params = [bigquery.ScalarQueryParameter("user_id", "STRING", user_id)]
    bq_client = bigquery.Client(project=settings.gcp_project_id)
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(
        None, partial(_run_parameterized_query, bq_client, sql, params)
    )
    bq_client.close()

    names = await _resolve_user_names([user_id], settings.slack_bot_token)
    display_name = names.get(user_id, user_id)

    return templates.TemplateResponse(
        request=request,
        name="user_detail.html",
        context={
            "user_id": user_id,
            "display_name": display_name,
            "entries": rows,
            "days": days,
        },
    )
