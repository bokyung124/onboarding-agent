"""카테고리 정의 — 단일 진실 소스(SSOT)."""

from typing import Literal

CategorySlug = Literal["all", "marketing", "tech", "tools"]

# (slug, LLM용 한국어 이름, UI 레이블, Slack 모달 레이블)
CATEGORY_DEFS: list[tuple[str, str, str, str]] = [
    ("all", "전체", "전체검색", "전체 데이터"),
    ("marketing", "마케팅", "마케팅", "마케팅 (Marketing)"),
    ("tech", "개발", "개발", "개발 (Dev)"),
    ("tools", "Tools", "Tools", "툴 (Tools)"),
]

CATEGORY_NAMES: dict[str, str] = {slug: name for slug, name, *_ in CATEGORY_DEFS}

# 온보딩 전용 카테고리
OnboardingCategorySlug = Literal["all", "seo", "crm", "aso", "pa", "ua", "cro", "tech"]

ONBOARDING_CATEGORY_DEFS: list[tuple[str, str, str, str]] = [
    ("all", "전체", "전체검색", "전체 온보딩"),
    ("seo", "SEO", "SEO", "SEO"),
    ("crm", "CRM", "CRM", "CRM"),
    ("aso", "ASO", "ASO", "ASO"),
    ("pa", "PA", "PA", "PA"),
    ("ua", "UA", "UA", "UA"),
    ("cro", "CRO", "CRO", "CRO"),
    ("tech", "개발", "개발", "개발 (Dev)"),
]

ONBOARDING_CATEGORY_NAMES: dict[str, str] = {
    slug: name for slug, name, *_ in ONBOARDING_CATEGORY_DEFS
}
