---
name: python-fastapi
description: Python/FastAPI 백엔드 개발 가이드라인. Python 파일, FastAPI 라우터, Pydantic 모델, async 서비스 함수를 작성하거나 수정할 때 사용.
---

# Python/FastAPI Guidelines

## Router Pattern

```python
from fastapi import APIRouter, Depends, HTTPException
from app.models.request import SomeRequest
from app.models.response import SomeResponse
from app.services.some_service import SomeService

router = APIRouter(prefix="/endpoint", tags=["endpoint"])

@router.post("/", response_model=SomeResponse)
async def handle(req: SomeRequest, svc: SomeService = Depends()):
    result = await svc.execute(req)
    if not result:
        raise HTTPException(status_code=404, detail="Not found")
    return result
```

## Pydantic Models

- Request: `BaseModel` + field validation
- Response: `model_config = ConfigDict(from_attributes=True)`
- 모든 필드에 `Field(description=...)` 추가 (OpenAPI 문서용)

```python
from pydantic import BaseModel, Field

class SearchRequest(BaseModel):
    department: str = Field(description="분야 slug, e.g. 'marketing-consulting'")
    query: str = Field(description="자연어 검색 질문", min_length=1)

class Source(BaseModel):
    title: str
    url: str
    block_id: str | None = None

class SearchResponse(BaseModel):
    answer: str = Field(description="인용이 포함된 생성 답변")
    sources: list[Source]
    department: str
```

## Service Layer

- 클래스 기반, async 메서드
- `__init__`으로 의존성 주입 (테스트 용이)
- 도메인 예외를 raise하고, 라우터에서 HTTPException으로 변환

## Async Rules

- 모든 I/O 함수는 `async`
- `httpx.AsyncClient` 사용 (blocking `requests` 금지)
- 외부 API 호출 시 timeout 설정 필수

## Error Handling

- `main.py`에 글로벌 예외 핸들러로 일관된 에러 응답
- 에러 포맷: `{"detail": "message"}`
- `structlog` 또는 stdlib `logging`으로 예외 로깅
