"""Gemini API로 RAG 기반 답변을 생성한다."""

import logging

from google import genai
from google.genai import types
from pydantic import BaseModel as PydanticBaseModel

from app.models.categories import CATEGORY_NAMES
from app.models.domain import ChunkResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
당신은 사내 온보딩 도우미입니다.
아래 제공되는 사내 문서 및 슬랙 대화 컨텍스트만을 기반으로 질문에 답변하세요.

규칙:
1. 컨텍스트에 없는 내용은 답변하지 마세요. "관련 문서를 찾지 못했습니다"라고 답하세요.
2. 답변 내에서 출처를 [출처 N] 형식으로 인라인 인용하세요.
3. 한국어로 답변하세요.
4. 간결하고 실용적으로 답변하세요.
5. Slack mrkdwn 형식으로 출력하세요:
   - 굵게: *텍스트* (별표 1개, **아님**)
   - 닫는 * 뒤에 한글이 바로 오면 볼드 미적용 — 반드시 공백 추가 (예: *구글 폼* 을 통해)
   - 목록: - 항목 (하이픈, *아님*)
   - 제목: *제목* (별표 1개로 강조)
   - ### 헤딩이나 **굵게** 같은 마크다운 문법 사용 금지
6. 사람 이름을 언급할 때 @ 기호를 사용하지 마세요. 이름만 쓰세요.
7. cited_indices 필드에 실제로 인용한 출처 번호(숫자만)를 리스트로 반환하세요."""


class _LLMResult(PydanticBaseModel):
    answer: str
    cited_indices: list[int]  # 1-based, 실제 인용한 [출처 N] 번호 목록


class LLMService:
    def __init__(self, client: genai.Client, model: str = "gemini-3-flash-preview"):
        self._client = client
        self._model = model

    async def generate_answer(
        self, query: str, category: str, chunks: list[ChunkResult]
    ) -> tuple[str, list[int]]:
        """검색된 청크를 컨텍스트로 사용하여 RAG 답변과 인용 인덱스를 반환한다."""
        if not chunks:
            return "관련 문서를 찾지 못했습니다. 다른 검색어로 시도해 주세요.", []

        context = self._build_context(chunks)
        cat_name = CATEGORY_NAMES.get(category, category)

        user_prompt = f"""카테고리: {cat_name}
질문: {query}

컨텍스트:
---
{context}
---

위 컨텍스트를 기반으로 질문에 답변하세요."""

        response = self._client.models.generate_content(
            model=self._model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.3,
                response_mime_type="application/json",
                response_schema=_LLMResult,
            ),
        )

        result = response.parsed
        if result is None:
            logger.warning("structured output parsing failed, falling back to raw text")
            return response.text or "답변을 생성하지 못했습니다.", []
        return result.answer, result.cited_indices

    def _build_context(self, chunks: list[ChunkResult]) -> str:
        """청크 목록을 번호 매겨진 컨텍스트 문자열로 변환한다."""
        parts: list[str] = []
        for i, chunk in enumerate(chunks, 1):
            source_label = "슬랙 채널" if chunk.source_type == "slack" else "문서"
            date_str = f", 최종수정: {chunk.last_edited_at[:10]}" if chunk.last_edited_at else ""
            header = (
                f"[출처 {i}] ({source_label}: {chunk.page_title},"
                f" 경로: {chunk.breadcrumb}{date_str})"
            )
            if chunk.parent_content:
                content = (
                    f"[관련 섹션]\n{chunk.content}\n\n"
                    f"[참고: 전체 페이지]\n{chunk.parent_content[:1500]}"
                )
            else:
                content = chunk.content
            parts.append(f"{header}\n{content}\n")
        return "\n".join(parts)
