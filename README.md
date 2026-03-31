# Onboarding Agent

노션과 슬랙 데이터를 기반으로 사내 문서와 대화를 검색해 답변을 생성하는 RAG(Retrieval-Augmented Generation) 기반 사내 온보딩 에이전트.

분야(카테고리)를 선택하고 질문을 입력하면 관련 노션 페이지와 슬랙 스레드를 검색해 **답변과 출처**를 함께 제공한다.

---

## Architecture

```
Notion API ─→ [Airflow: Extract] ─→ BigQuery Raw (notion)
Slack  API ─→ [Airflow: Extract] ─→ BigQuery Raw (slack)
                                        ↓
                              [dbt: Transform]
                                        ↓
                    BigQuery Mart (mart_notion_chunks + mart_slack_chunks)
                                        ↓
                        mart_enterprise_chunks (UNION view)
                                        ↓
                    [Airflow: Embed (Gemini)] → mart_enterprise_vectors
                                        ↓
                        [FastAPI + Gemini] → 사용자 응답
```

---

## Tech Stack

| 역할 | 기술 |
|------|------|
| API 서버 | Python 3.12+, FastAPI, uvicorn |
| LLM / 임베딩 | Gemini 3 Flash / gemini-embedding-2-preview (768 dim) |
| 벡터 검색 | BigQuery VECTOR_SEARCH |
| 데이터 웨어하우스 | Google BigQuery |
| 데이터 변환 | dbt (BigQuery adapter) |
| 파이프라인 오케스트레이션 | Apache Airflow |
| Notion 추출 | notion-client (async) |
| Slack 추출 / 봇 | slack-sdk (async, Socket Mode) |
| 인메모리 캐시 | cachetools (TTL) |
| 패키지 관리 | uv |
| 린트 / 포맷 | ruff |
| 테스트 | pytest, pytest-asyncio |
| 컨테이너 | Docker (Cloud Run 배포) |

---

## Quick Start

### 사전 요구 사항

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) 설치
- GCP 프로젝트 및 서비스 계정 (BigQuery + Gemini API 접근 권한)
- `.env` 파일 (아래 환경 변수 참고)

### 로컬 실행

```bash
# 의존성 설치
uv sync

# 개발 서버 실행
uv run uvicorn app.main:app --reload
```

서버가 실행되면 `http://localhost:8000`에서 접근 가능하다.
Swagger UI: `http://localhost:8000/docs`

---

## Environment Variables

`.env` 파일을 프로젝트 루트에 생성한다.

### 서빙 레이어 (필수)

| 변수 | 설명 |
|------|------|
| `GCP_PROJECT_ID` | GCP 프로젝트 ID |
| `GEMINI_API_KEY` | Gemini API 키 (답변 생성 + 임베딩) |

### 서빙 레이어 (선택)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `BQ_DATASET` | `onboarding_agent` | BigQuery 데이터셋 이름 |
| `GEMINI_MODEL` | `gemini-3-flash-preview` | 답변 생성 모델 |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-2-preview` | 임베딩 모델 |
| `SLACK_BOT_TOKEN` | — | Slack 봇 토큰 (Socket Mode 통합 사용 시) |
| `SLACK_APP_TOKEN` | — | Slack 앱 토큰 (`xapp-...`, Socket Mode 사용 시) |
| `SLACK_WORKSPACE` | — | Slack 워크스페이스 서브도메인 (permalink 생성용) |
| `SEARCH_TOP_K` | `50` | 벡터 검색 후보 수 |
| `SEARCH_RESULT_LIMIT` | `8` | 최종 반환 소스 수 |
| `SEARCH_DISTANCE_THRESHOLD` | `0.7` | 유사도 임계값 |
| `CACHE_TTL_SECONDS` | `3600` | 캐시 TTL (초) |
| `CACHE_MAX_SIZE` | `500` | 캐시 최대 항목 수 |

### 파이프라인 전용

| 변수 | 설명 |
|------|------|
| `NOTION_API_KEY` | 노션 통합 토큰 |
| `NOTION_ROOT_PAGE_ID` | 루트 페이지 ID (없으면 전체 워크스페이스 크롤링) |
| `SLACK_BOT_TOKEN` | Slack Bot 토큰 |
| `SLACK_CHANNEL_IDS` | 대상 채널 ID (쉼표 구분, 없으면 전체 public 채널) |

---

## API Reference

### `GET /health`

서버 상태 확인.

```json
// Response
{ "status": "ok", "version": "0.1.0" }
```

---

### `GET /categories`

검색 가능한 카테고리 목록 반환.

```json
// Response
[
  { "slug": "all",       "name": "전체검색" },
  { "slug": "marketing", "name": "마케팅" },
  { "slug": "tech",      "name": "개발" },
  { "slug": "tools",     "name": "Tools" }
]
```

---

### `POST /search`

질문에 대한 RAG 답변과 출처를 반환한다.

**Request Body**

```json
{
  "category": "all",
  "query": "온보딩 절차는 어떻게 되나요?",
  "client_name": "optional filter",
  "tags": "optional filter"
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `category` | string | ✓ | `all` \| `marketing` \| `tech` \| `tools` |
| `query` | string | ✓ | 질문 (2~500자) |
| `client_name` | string | — | 클라이언트 필터 |
| `tags` | string | — | 태그 필터 (부분 일치) |

**Response**

```json
{
  "answer": "온보딩은 입사 첫 주에 [1] HR 포털에서 계정을 생성하고...",
  "sources": [
    {
      "title": "신입 온보딩 가이드",
      "url": "https://www.notion.so/...",
      "breadcrumb": "HR > 온보딩",
      "page_id": "abc123",
      "source_type": "notion"
    },
    {
      "title": "#onboarding",
      "url": "https://yourworkspace.slack.com/archives/...",
      "breadcrumb": "#onboarding",
      "page_id": "C012AB3CD/...",
      "source_type": "slack"
    }
  ],
  "category": "all",
  "metadata": {
    "chunks_retrieved": 50,
    "latency_ms": 1243
  }
}
```

---

## Search Flow

1. `POST /search` 수신 → 캐시 확인
2. 쿼리를 Gemini 임베딩 API로 벡터화 (768 dim)
3. BigQuery `VECTOR_SEARCH`로 유사 청크 검색 (카테고리 필터 적용)
4. 상위 3개 Notion 청크에 부모 페이지 컨텍스트 추가
5. Gemini 3 Flash로 RAG 답변 생성 (구조화 출력 — 인용 인덱스 포함)
6. 중복 소스 제거 후 응답 반환 + 캐시 저장 (TTL 1시간)

---

## Search Categories

| Slug | 이름 | 범위 |
|------|------|------|
| `all` | 전체검색 | 노션 전체 + 슬랙 전체 |
| `marketing` | 마케팅 | 노션 Marketing 팀스페이스 + 마케팅 관련 슬랙 채널 |
| `tech` | 개발 | 노션 Tech 팀스페이스 + 개발 관련 슬랙 채널 |
| `tools` | Tools | 노션 Tools 팀스페이스 + 툴 관련 슬랙 채널 |

슬랙 채널 → 카테고리 매핑은 `dbt_notion/seeds/slack_channel_categories.csv`에서 관리한다.

---

## Data Pipeline

Airflow DAG 3개로 구성된다. DAG 파일 위치: `dags/`

### `notion_extract_load`
- **스케줄**: 매일 06:00 KST (21:00 UTC)
- 노션 API에서 페이지/블록/데이터베이스를 BFS 크롤링 → BigQuery raw 테이블 적재
- 완료 시 `enterprise_embed` DAG 자동 트리거

### `slack_extract_load`
- **스케줄**: 매일 06:30 KST (21:30 UTC)
- Slack API에서 채널/스레드를 추출 → BigQuery raw 테이블 적재
- 완료 시 `enterprise_embed` DAG 자동 트리거

### `enterprise_embed`
- **트리거**: `notion_extract_load` 또는 `slack_extract_load` 완료 시
- dbt 변환 실행 → 변경된 청크 감지 → Gemini 임베딩 생성 (배치 100) → `mart_enterprise_vectors` 적재

### dbt 모델 레이어

```
staging/     # raw → 정제 (view)
intermediate/ # breadcrumb, 블록 조립, 스레드 그룹핑 (table)
mart/        # 최종 문서/청크 + UNION view
```

---

## Project Structure

```
├── app/                              # FastAPI 서빙 레이어
│   ├── main.py                       # 앱 진입점 + lifespan
│   ├── config.py                     # Pydantic Settings (환경 변수)
│   ├── cache.py                      # TTL 인메모리 캐시
│   ├── routers/
│   │   ├── health.py                 # GET /health
│   │   ├── categories.py             # GET /categories
│   │   └── search.py                 # POST /search
│   ├── services/
│   │   ├── embedder.py               # 쿼리 → Gemini 임베딩
│   │   ├── vector_search.py          # BigQuery VECTOR_SEARCH
│   │   ├── llm.py                    # Gemini RAG 답변 생성
│   │   ├── reranker.py               # 크로스 인코더 리랭킹
│   │   ├── search_orchestrator.py    # 전체 검색 흐름 조율
│   │   ├── slack_bot.py              # Slack Socket Mode 봇
│   │   └── slack_formatter.py        # Slack mrkdwn 포맷팅
│   └── models/
│       ├── request.py                # SearchRequest
│       ├── response.py               # SearchResponse, Source
│       └── domain.py                 # ChunkResult (내부용)
│
├── pipeline/                         # 데이터 파이프라인
│   ├── extract/
│   │   ├── notion_extractor.py       # Notion BFS 크롤링
│   │   ├── rate_limiter.py           # Semaphore + exponential backoff
│   │   ├── slack_extractor.py        # Slack 채널/스레드 추출
│   │   └── slack_rate_limiter.py     # Slack rate limit 처리
│   └── embed/
│       └── generate_embeddings.py    # 증분 임베딩 생성
│
├── dags/                             # Airflow DAG 정의
│   ├── notion_extract_load.py
│   ├── slack_extract_load.py
│   └── enterprise_embed.py
│
├── dbt_notion/                       # dbt 프로젝트
│   ├── seeds/
│   │   └── slack_channel_categories.csv
│   └── models/
│       ├── staging/
│       ├── intermediate/
│       └── mart/
│
├── scripts/                          # 운영 스크립트
│   ├── deploy.sh                     # Cloud Run 배포
│   ├── backfill_slack_channels.py    # Slack 채널 백필
│   └── run_embeddings.py             # 수동 임베딩 실행
│
├── tests/                            # pytest 테스트
├── Dockerfile
└── pyproject.toml
```

---

## Development Guide

```bash
# 테스트 실행
uv run pytest -v

# 린트 + 포맷
uv run ruff check . && uv run ruff format .

# dbt 변환 실행
cd dbt_notion && dbt run

# dbt 테스트
cd dbt_notion && dbt test
```

### 컨벤션

- 서빙 레이어(`app/`)에서 Notion/Slack API 직접 호출 금지 — BigQuery만 조회
- 모든 I/O 함수는 `async`; BigQuery 동기 클라이언트는 `run_in_executor()` 래핑
- 모든 함수 시그니처에 타입 어노테이션 필수
- 임베딩 모델은 파이프라인과 서빙에서 반드시 동일 (`gemini-embedding-2-preview`)
- 환경변수 절대 하드코딩 금지
- 테스트에서 외부 API (BigQuery, Gemini, Notion, Slack)는 mock 처리

---

## Deployment

### Docker

```bash
# 이미지 빌드
docker build -t onboarding-agent:latest .

# 컨테이너 실행
docker run -p 8080:8080 \
  -e GCP_PROJECT_ID=<project> \
  -e GEMINI_API_KEY=<key> \
  onboarding-agent:latest
```

### Cloud Run (GCP)

```bash
# .env 파일 설정 후 배포 스크립트 실행
./scripts/deploy.sh
```

배포 스크립트가 Docker 이미지 빌드 → GCR 푸시 → Cloud Run 서비스 생성/업데이트를 자동으로 처리한다.

---

## BigQuery Tables

| 레이어 | 테이블 | 설명 |
|--------|--------|------|
| Raw | `raw_notion_pages` | 노션 페이지 메타데이터 |
| Raw | `raw_notion_blocks` | 노션 블록 (텍스트, 헤딩 등) |
| Raw | `raw_slack_messages` | 슬랙 메시지 (채널/스레드) |
| Raw | `raw_slack_users` | 슬랙 유저 정보 |
| Mart | `mart_notion_chunks` | 청킹된 노션 문서 |
| Mart | `mart_slack_chunks` | 슬랙 스레드 청크 |
| Mart | `mart_enterprise_chunks` | 통합 UNION view (Notion + Slack) |
| Mart | `mart_enterprise_vectors` | Gemini 임베딩 벡터 (VECTOR_SEARCH 대상) |
