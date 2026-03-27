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
def mock_bq_client() -> MagicMock:
    return MagicMock()
