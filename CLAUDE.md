# Onboarding Agent

노션 + 슬랙 데이터 기반 사내 온보딩 에이전트. 분야를 선택하고 질문을 입력하면 관련 노션 페이지와 슬랙 대화를 검색해 답변과 출처를 제공한다.

## 아키텍처

```
Notion API ─→ [Airflow: Extract] ─→ BigQuery Raw (notion)
Slack  API ─→ [Airflow: Extract] ─→ BigQuery Raw (slack)
                                        ↓
                              [dbt: Transform]
                                        ↓
                    BigQuery Mart (notion_chunks + slack_chunks)
                                        ↓
                        mart_enterprise_chunks (UNION view)
                                        ↓
                    [Airflow: Embed (Gemini)] → mart_enterprise_vectors
                                        ↓
                        [FastAPI + Gemini] → 사용자 응답
```

## 검색 카테고리

- 전체검색 (`all`) — 모든 문서에서 검색 (기본값)
- 마케팅 (`marketing`) — onboarding manual + {마케팅} 프로젝트
- 개발 (`tech`) — Tech
- Tools (`tools`) — Tools

노션: 팀스페이스 하위 최상위 페이지 기준으로 카테고리를 분류한다. 슬랙: `dbt_notion/seeds/slack_channel_categories.csv`의 채널→카테고리 매핑을 따른다. Airflow로 추출, dbt로 변환, Gemini 임베딩으로 벡터화하여 BigQuery Vector Search로 검색한다.

## Tech Stack

- Python 3.12+, FastAPI, uvicorn
- Notion API (`notion-client` async SDK) — 파이프라인 전용
- Slack API (`slack-sdk` async SDK) — 파이프라인 전용
- Gemini API (`google-genai` SDK) — 답변 생성 + 임베딩 (`text-embedding-004`)
- BigQuery (`google-cloud-bigquery`) — 데이터 웨어하우스 + Vector Search
- dbt (`dbt-bigquery`) — 데이터 변환 (staging → intermediate → mart)
- Airflow — 데이터 파이프라인 오케스트레이션 (기존 서버 활용)
- Pydantic v2 for request/response models
- cachetools — TTL 인메모리 캐시
- pytest + pytest-asyncio for testing
- uv for dependency management
- ruff for linting & formatting

## Project Structure

```
├── app/                          # FastAPI 서빙 레이어
│   ├── main.py                   # FastAPI 앱 + lifespan
│   ├── config.py                 # pydantic-settings
│   ├── cache.py                  # TTL 인메모리 캐시
│   ├── routers/
│   │   ├── health.py             # GET /health
│   │   ├── categories.py         # GET /categories
│   │   └── search.py             # POST /search
│   ├── services/
│   │   ├── embedder.py           # 쿼리 → Gemini 임베딩
│   │   ├── vector_search.py      # BigQuery VECTOR_SEARCH
│   │   ├── llm.py                # Gemini RAG 답변 생성
│   │   └── search_orchestrator.py
│   └── models/
│       ├── request.py            # SearchRequest
│       ├── response.py           # SearchResponse, Source
│       └── domain.py             # ChunkResult (내부용)
├── pipeline/                     # 데이터 파이프라인
│   ├── extract/
│   │   ├── notion_extractor.py   # Notion API 추출 (BFS 재귀 순회)
│   │   ├── rate_limiter.py       # Notion Semaphore + exponential backoff
│   │   ├── slack_extractor.py    # Slack API 추출 (채널/스레드)
│   │   └── slack_rate_limiter.py # Slack rate limit
│   └── embed/
│       └── generate_embeddings.py # 증분 Gemini 임베딩 생성 (통합 mart)
├── dags/                         # Airflow DAGs
│   ├── notion_extract_load.py    # Notion Extract & Load (일 1회)
│   ├── slack_extract_load.py     # Slack Extract & Load (일 1회)
│   ├── enterprise_embed.py       # 통합 dbt run → 임베딩 생성
│   └── notion_embed.py           # (deprecated, enterprise_embed으로 대체)
├── dbt_notion/                   # dbt 프로젝트
│   ├── seeds/                    # 채널→카테고리 매핑 CSV
│   └── models/
│       ├── staging/notion/       # Notion raw → 정제 (view)
│       ├── staging/slack/        # Slack raw → 정제 (view)
│       ├── intermediate/notion/  # breadcrumb, 블록 조립 (table)
│       ├── intermediate/slack/   # 스레드 그룹핑, 채널 카테고리 (table)
│       └── mart/                 # 문서/청킹 + 통합 UNION view
└── tests/
```

## Conventions

- **서빙 레이어(`app/`)에서 Notion/Slack API 직접 호출 금지** — BigQuery만 조회한다.
- 모든 Notion/Slack API 호출은 `pipeline/extract/` 경유. rate_limiter 필수.
- 모든 응답 모델에 `sources: list[Source]` 필드 포함 (페이지 제목, URL, breadcrumb).
- 임베딩 모델은 파이프라인과 서빙에서 반드시 동일 모델 사용 (`text-embedding-004`).
- 환경변수: `GCP_PROJECT_ID`, `GEMINI_API_KEY`, `NOTION_API_KEY`, `SLACK_BOT_TOKEN`. 절대 하드코딩 금지.
- 모든 함수 시그니처에 타입 어노테이션 필수.
- `ruff`로 lint, `ruff format`으로 포맷팅.
- 모든 I/O 함수는 `async`. BigQuery 동기 클라이언트는 `run_in_executor()`로 래핑.
- 테스트는 `pytest-asyncio` 사용. 외부 API (BigQuery, Gemini, Notion, Slack)는 mock 처리.

## Commands

```bash
uv run uvicorn app.main:app --reload        # 개발 서버
uv run pytest -v                             # 테스트
uv run ruff check . && uv run ruff format .  # lint + format

# dbt
cd dbt_notion && dbt run                     # 변환 실행
cd dbt_notion && dbt test                    # dbt 테스트
```

## Environment Variables

- `GCP_PROJECT_ID` — GCP 프로젝트 ID (필수)
- `BQ_DATASET` — BigQuery 데이터셋 (기본: `onboarding_agent`)
- `GEMINI_API_KEY` — Gemini API 키 (필수, 답변 생성 + 임베딩)
- `NOTION_API_KEY` — 노션 통합 토큰 (파이프라인 전용)
- `NOTION_ROOT_PAGE_ID` — 루트 페이지 ID (선택, 없으면 전체 워크스페이스 검색)
- `SLACK_BOT_TOKEN` — Slack Bot 토큰 (파이프라인 전용, 필수)
- `SLACK_CHANNEL_IDS` — 대상 채널 ID (쉼표 구분, 선택 — 없으면 전체 public 채널)
- `SLACK_WORKSPACE` — Slack 워크스페이스 서브도메인 (permalink 생성용)

## BigQuery Tables

| 레이어 | 테이블 | 설명 |
|--------|--------|------|
| Raw | `raw_notion_pages` | 노션 페이지 메타데이터 |
| Raw | `raw_notion_blocks` | 노션 블록 (텍스트, 헤딩 등) |
| Raw | `raw_notion_databases` | 노션 데이터베이스 스키마 |
| Staging | `stg_notion_pages` | 정제된 페이지 (view) |
| Staging | `stg_notion_blocks` | 정제된 블록 (view) |
| Intermediate | `int_notion_page_breadcrumbs` | 재귀 CTE 경로 + 카테고리 분류 |
| Intermediate | `int_notion_page_content` | 블록 → 마크다운 조립 |
| Mart | `mart_notion_documents` | 최종 문서 |
| Mart | `mart_notion_chunks` | 청킹된 문서 |
| Raw | `raw_slack_messages` | 슬랙 메시지 (채널/스레드) |
| Raw | `raw_slack_users` | 슬랙 유저 정보 |
| Staging | `stg_slack_messages` | 정제된 메시지 + 타임스탬프 변환 (view) |
| Staging | `stg_slack_users` | 정제된 유저 (view) |
| Intermediate | `int_slack_threads` | 스레드 그룹핑 (STRING_AGG) |
| Intermediate | `int_slack_channel_categories` | 채널→카테고리 매핑 |
| Mart | `mart_slack_chunks` | 슬랙 스레드 청크 |
| Mart | `mart_enterprise_chunks` | 통합 UNION view (Notion + Slack) |
| Mart | `mart_enterprise_vectors` | 통합 임베딩 벡터 (VECTOR_SEARCH) |
