from fastapi import APIRouter, Request

from app.models.request import SearchRequest
from app.models.response import SearchResponse

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(request: Request, body: SearchRequest) -> SearchResponse:
    """부서별 질문 검색 및 RAG 기반 답변을 반환한다."""
    cache = request.app.state.cache
    orchestrator = request.app.state.orchestrator

    # 캐시 확인
    cached = cache.get(body.category, body.query)
    if cached:
        return cached

    # 검색 실행
    response = await orchestrator.search(body)

    # 캐시 저장
    cache.set(body.category, body.query, response)

    return response
