# Notion API Patterns Reference

## 1. 인증 & 권한

통합(Integration)은 대상 페이지에 명시적으로 공유되어야 한다. 검색 결과가 비면 통합이 해당 페이지에 접근 권한이 있는지 확인.

필수 권한: Read content.

## 2. 페이지네이션 범용 패턴

```python
async def paginate(endpoint_fn, **kwargs) -> list[dict]:
    results = []
    cursor = None
    while True:
        resp = await endpoint_fn(**kwargs, start_cursor=cursor)
        results.extend(resp["results"])
        if not resp["has_more"]:
            break
        cursor = resp["next_cursor"]
    return results
```

## 3. Rich Text → Markdown 변환

```python
def rich_text_to_markdown(rich_texts: list[dict]) -> str:
    parts = []
    for rt in rich_texts:
        text = rt["plain_text"]
        ann = rt["annotations"]
        if ann["bold"]: text = f"**{text}**"
        if ann["italic"]: text = f"*{text}*"
        if ann["code"]: text = f"`{text}`"
        if rt.get("href"): text = f"[{text}]({rt['href']})"
        parts.append(text)
    return "".join(parts)
```

## 4. 데이터베이스 쿼리 (필터 포함)

```python
async def query_database(db_id: str, department: str) -> list[dict]:
    response = await notion.databases.query(
        database_id=db_id,
        filter={"property": "Department", "select": {"equals": department}},
        sorts=[{"property": "Last edited time", "direction": "descending"}],
    )
    return response["results"]
```

필터 타입: `select`, `multi_select`, `rich_text`, `title`, `checkbox`, `date`, `number`.
복합 필터: `{"and": [...]}` 또는 `{"or": [...]}`.

## 5. 에러 핸들링 & Rate Limit

```python
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from notion_client import APIResponseError

@retry(
    retry=retry_if_exception_type(APIResponseError),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
)
async def safe_notion_call(fn, **kwargs):
    return await fn(**kwargs)
```

주요 에러 코드:
| 코드 | 원인 | 대응 |
|------|------|------|
| 401 | 잘못된 토큰 | 노션 통합 설정에서 재생성 |
| 403 | 페이지 접근 권한 없음 | 노션에서 통합에 페이지 공유 |
| 404 | 페이지 삭제됨 | 인덱스에서 제거 |
| 429 | Rate limit | 재시도 (backoff) |
| 502 | 노션 장애 | 재시도 |

## 6. 전체 크롤링 캐싱 전략

전체 워크스페이스 크롤링은 API 호출이 많으므로:
- 결과를 로컬 JSON/SQLite에 캐싱
- 마지막 크롤링 시각 기록
- `last_edited_time` 기준으로 변경된 페이지만 갱신
- 초기 크롤링 시 rate limit 고려해 `asyncio.Semaphore(3)` 사용
