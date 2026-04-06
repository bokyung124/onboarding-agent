import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.models.request import SearchRequest
from app.models.response import SearchResponse

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(request: Request, body: SearchRequest) -> SearchResponse:
    """부서별 질문 검색 및 RAG 기반 답변을 반환한다."""
    orchestrator = request.app.state.orchestrator
    timeout: float = request.app.state.settings.search_timeout_seconds
    try:
        return await asyncio.wait_for(
            orchestrator.search(body, user_id=body.user_id), timeout=timeout
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="검색 요청이 시간 초과되었습니다.")
