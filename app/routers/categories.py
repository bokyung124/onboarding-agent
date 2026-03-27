from fastapi import APIRouter

from app.models.response import Category, CategoryListResponse

router = APIRouter(tags=["categories"])

CATEGORIES = [
    Category(slug="all", name="전체검색"),
    Category(slug="marketing", name="마케팅"),
    Category(slug="tech", name="개발"),
    Category(slug="tools", name="Tools"),
]


@router.get("/categories", response_model=CategoryListResponse)
async def list_categories() -> CategoryListResponse:
    return CategoryListResponse(categories=CATEGORIES)
