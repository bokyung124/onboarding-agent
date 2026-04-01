from fastapi import APIRouter, Request

from app.models.response import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse()


@router.post("/admin/cache/clear")
async def clear_cache(request: Request) -> dict:
    """인메모리 검색 캐시를 초기화한다."""
    cleared = request.app.state.cache.clear()
    return {"cleared": cleared}
