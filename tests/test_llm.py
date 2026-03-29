"""LLM 서비스 테스트."""

from app.models.domain import ChunkResult
from app.services.llm import LLMService


def test_build_context():
    """컨텍스트 빌드가 번호 매겨진 출처 형식이어야 한다."""
    chunks = [
        ChunkResult(
            chunk_id="c1",
            page_id="p1",
            page_title="문서 A",
            breadcrumb="팀 > 문서 A",
            category="tech",
            content="내용 1",
            source_url="https://notion.so/p1",
            source_type="notion",
            distance=0.1,
        ),
        ChunkResult(
            chunk_id="c2",
            page_id="p2",
            page_title="문서 B",
            breadcrumb="팀 > 문서 B",
            category="tech",
            content="내용 2",
            source_url="https://notion.so/p2",
            source_type="notion",
            distance=0.2,
        ),
    ]

    llm = LLMService.__new__(LLMService)
    context = llm._build_context(chunks)

    assert "[출처 1]" in context
    assert "[출처 2]" in context
    assert "문서 A" in context
    assert "문서 B" in context
