"""Gemini API로 RAG 기반 답변을 생성한다."""

from google import genai
from google.genai import types

from app.models.domain import ChunkResult

CATEGORY_NAMES = {
    "all": "전체",
    "marketing": "마케팅",
    "tech": "개발",
    "tools": "Tools",
}

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
   - 목록: - 항목 (하이픈, *아님*)
   - 제목: *제목* (별표 1개로 강조)
   - ### 헤딩이나 **굵게** 같은 마크다운 문법 사용 금지
6. 사람 이름을 언급할 때 @ 기호를 사용하지 마세요. 이름만 쓰세요."""


class LLMService:
    def __init__(self, client: genai.Client, model: str = "gemini-3-flash-preview"):
        self._client = client
        self._model = model

    async def generate_answer(self, query: str, category: str, chunks: list[ChunkResult]) -> str:
        """검색된 청크를 컨텍스트로 사용하여 RAG 답변을 생성한다."""
        if not chunks:
            return "관련 문서를 찾지 못했습니다. 다른 검색어로 시도해 주세요."

        context = self._build_context(chunks)
        cat_name = CATEGORY_NAMES.get(category, category)

        user_prompt = f"""카테고리: {cat_name}
질문: {query}

컨텍스트:
---
{context}
---

위 컨텍스트를 기반으로 질문에 답변하세요. 반드시 [출처 N] 형식으로 인용을 포함하세요."""

        response = self._client.models.generate_content(
            model=self._model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.3,
                max_output_tokens=2048,
            ),
        )
        import logging

        logging.getLogger(__name__).warning("Gemini response: %s", response)
        return response.text or "답변을 생성하지 못했습니다. 다시 시도해 주세요."

    def _build_context(self, chunks: list[ChunkResult]) -> str:
        """청크 목록을 번호 매겨진 컨텍스트 문자열로 변환한다."""
        parts: list[str] = []
        for i, chunk in enumerate(chunks, 1):
            source_label = "슬랙 채널" if chunk.source_type == "slack" else "문서"
            header = f"[출처 {i}] ({source_label}: {chunk.page_title}, 경로: {chunk.breadcrumb})"
            parts.append(f"{header}\n{chunk.content}\n")
        return "\n".join(parts)
