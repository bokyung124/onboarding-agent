from fastapi import APIRouter

from app.models.categories import CATEGORY_DEFS
from app.models.response import Category, CategoryListResponse

router = APIRouter(tags=["categories"])

CATEGORIES = [Category(slug=slug, name=label) for slug, _, label, _ in CATEGORY_DEFS]


@router.get("/categories", response_model=CategoryListResponse)
async def list_categories() -> CategoryListResponse:
    return CategoryListResponse(categories=CATEGORIES)
