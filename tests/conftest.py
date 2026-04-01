from unittest.mock import MagicMock

import pytest

from app.models.domain import ChunkResult


@pytest.fixture
def sample_chunks() -> list[ChunkResult]:
    return [
        ChunkResult(
            chunk_id="page1_0",
            page_id="page-1",
            page_title="SI 프로젝트 세팅 가이드",
            breadcrumb="Tech > 프로젝트 관리 > 세팅 가이드",
            category="tech",
            content="신규 프로젝트 시작 시 Jira 프로젝트를 먼저 생성합니다.",
            source_url="https://notion.so/page-1",
            source_type="notion",
            distance=0.15,
        ),
        ChunkResult(
            chunk_id="page2_0",
            page_id="page-2",
            page_title="개발 환경 설정",
            breadcrumb="Tech > 프로젝트 관리 > 개발 환경",
            category="tech",
            content="Git 저장소를 클론한 후 Docker Compose로 로컬 환경을 구성합니다.",
            source_url="https://notion.so/page-2",
            source_type="notion",
            distance=0.22,
        ),
    ]


@pytest.fixture
def mock_embedder() -> MagicMock:
    embedder = MagicMock()
    embedder.embed_query.return_value = [0.1] * 768
    return embedder


@pytest.fixture
def sample_onboarding_chunks() -> list[ChunkResult]:
    return [
        ChunkResult(
            chunk_id="seo_page1_0",
            page_id="seo-basics",
            page_title="SEO 기초 가이드",
            breadcrumb="SEO > 온보딩 > 기초 가이드",
            category="seo",
            content="SEO의 기본 개념과 검색엔진 작동 원리를 설명합니다.",
            source_url="https://notion.so/seo-basics",
            source_type="notion",
            distance=0.1,
        ),
        ChunkResult(
            chunk_id="seo_page2_0",
            page_id="seo-tools",
            page_title="SEO 도구 사용법",
            breadcrumb="SEO > 온보딩 > 도구 사용법",
            category="seo",
            content="Google Search Console과 GA4 설정 방법을 안내합니다.",
            source_url="https://notion.so/seo-tools",
            source_type="notion",
            distance=0.15,
        ),
        ChunkResult(
            chunk_id="seo_page3_0",
            page_id="seo-workflow",
            page_title="SEO 업무 프로세스",
            breadcrumb="SEO > 온보딩 > 업무 프로세스",
            category="seo",
            content="키워드 리서치부터 콘텐츠 최적화까지 전체 워크플로우입니다.",
            source_url="https://notion.so/seo-workflow",
            source_type="notion",
            distance=0.2,
        ),
    ]


@pytest.fixture
def mock_bq_client() -> MagicMock:
    return MagicMock()
