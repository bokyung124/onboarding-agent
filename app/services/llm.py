"""Gemini API로 RAG 기반 답변을 생성한다."""

import asyncio
import logging
from functools import partial

from google import genai
from google.genai import types
from pydantic import BaseModel as PydanticBaseModel

from app.models.categories import CATEGORY_NAMES, ONBOARDING_CATEGORY_NAMES
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
7. cited_indices 필드에 실제로 인용한 출처 번호(숫자만)를 리스트로 반환하세요.
8. 답변 후, 사용자가 다음으로 궁금해할 만한 후속 질문 2~3개를 follow_up_questions에 포함하세요.
   - 현재 컨텍스트에서 파생되는 구체적인 질문이어야 합니다.
   - "더 알고 싶으시면" 같은 일반적인 질문은 피하세요.
   - 짧고 명확한 질문으로 작성하세요 (50자 이내).
9. 이전 대화가 제공되면 맥락을 참고하여 답변하되, 반드시 컨텍스트 문서를 기반으로 답변하세요."""

ONBOARDING_SYSTEM_PROMPT = """\
당신은 신규 입사자를 위한 온보딩 가이드입니다.
아래 제공되는 사내 온보딩 문서 컨텍스트를 기반으로, 신규 입사자가 바로 따라할 수 있도록 상세하게 안내하세요.

규칙:
1. 컨텍스트에 없는 내용은 답변하지 마세요. "관련 온보딩 문서를 찾지 못했습니다"라고 답하세요.
2. 답변 내에서 출처를 [출처 N] 형식으로 인라인 인용하세요.
3. 한국어로 답변하세요.
4. 단계별로 상세하게 설명하세요. 각 단계에서 구체적으로 무엇을 해야 하는지, 어떤 도구를 사용하는지, 주의사항은 무엇인지 포함하세요.
5. 컨텍스트에 있는 내용은 최대한 빠짐없이 포함하세요. 요약하지 말고 원문의 세부 사항을 충실히 전달하세요.
6. Slack mrkdwn 형식으로 출력하세요:
   - 굵게: *텍스트* (별표 1개, **아님**)
   - 닫는 * 뒤에 한글이 바로 오면 볼드 미적용 — 반드시 공백 추가 (예: *구글 폼* 을 통해)
   - 목록: - 항목 (하이픈, *아님*)
   - 제목: *제목* (별표 1개로 강조)
   - ### 헤딩이나 **굵게** 같은 마크다운 문법 사용 금지
7. 사람 이름을 언급할 때 @ 기호를 사용하지 마세요. 이름만 쓰세요.
8. cited_indices 필드에 실제로 인용한 출처 번호(숫자만)를 리스트로 반환하세요.
9. 답변 후, 신규 입사자가 다음으로 궁금해할 만한 후속 질문 2~3개를 follow_up_questions에 포함하세요.
   - 현재 컨텍스트에서 파생되는 구체적인 질문이어야 합니다.
   - "더 알고 싶으시면" 같은 일반적인 질문은 피하세요.
   - 짧고 명확한 질문으로 작성하세요 (50자 이내).
9. 이전 대화가 제공되면 맥락을 참고하여 답변하되, 반드시 컨텍스트 문서를 기반으로 답변하세요."""  # noqa: E501


CHECKLIST_SYSTEM_PROMPT = """\
당신은 신규 입사자를 위한 온보딩 학습 경로 설계자입니다.
아래 제공되는 온보딩 문서 컨텍스트를 분석하여, 해당 분야의 구조화된 학습 경로를 설계하세요.

규칙:
1. 컨텍스트를 분석하여 5~10단계의 논리적 학습 경로를 생성하세요.
2. 기초 → 심화 순서로 단계를 정렬하세요.
3. 각 단계의 title은 간결하게 (20자 이내), description은 2~3문장으로 작성하세요.
4. 각 단계의 search_query는 해당 단계의 상세 정보를 검색할 수 있는 구체적인 질문이어야 합니다.
5. 한국어로 작성하세요.
6. description은 Slack mrkdwn 형식으로 출력하세요:
   - 굵게: *텍스트* (별표 1개)
   - 목록: - 항목 (하이픈)
7. title 필드에 "{분야} 팀 온보딩 N단계" 형식으로 전체 제목을 작성하세요."""


class _ChecklistStep(PydanticBaseModel):
    step_number: int
    title: str
    description: str
    search_query: str


class _ChecklistResult(PydanticBaseModel):
    title: str  # "SEO 팀 온보딩 7단계"
    steps: list[_ChecklistStep]


class _LLMResult(PydanticBaseModel):
    answer: str
    cited_indices: list[int]  # 1-based, 실제 인용한 [출처 N] 번호 목록
    follow_up_questions: list[str] = []  # 후속 질문 2~3개


DECOMPOSE_SYSTEM_PROMPT = """\
당신은 사내 문서 검색 시스템의 질문 분석기입니다.
사용자 질문을 분석하여 검색에 적합한 형태로 분해하세요.

규칙:
1. 질문이 단순하면 (하나의 주제) needs_decomposition=false로 반환하세요.
2. 질문이 복합적이면 (여러 주제/단계) 2~3개의 단순 검색 쿼리로 분해하세요.
3. 각 하위 쿼리는 독립적으로 검색 가능한 구체적인 질문이어야 합니다.
4. 한국어로 작성하세요."""

REFORMULATE_SYSTEM_PROMPT = """\
당신은 사내 문서 검색 시스템의 쿼리 최적화 전문가입니다.
사용자의 원래 질문이 좋은 검색 결과를 가져오지 못했습니다.
검색 결과를 개선할 수 있도록 쿼리를 재구성하세요.

규칙:
1. 원래 질문의 의도를 유지하되, 다른 표현이나 동의어를 사용하세요.
2. 너무 구체적인 질문은 약간 일반화하고, 너무 일반적인 질문은 구체화하세요.
3. 검색에 적합한 키워드 중심의 간결한 쿼리로 변환하세요.
4. 한국어로 작성하세요.
5. reasoning에 왜 이렇게 변환했는지 간단히 설명하세요."""


class _DecomposeResult(PydanticBaseModel):
    needs_decomposition: bool
    sub_queries: list[str]


class _ReformulateResult(PydanticBaseModel):
    reformulated_query: str
    reasoning: str


class LLMService:
    def __init__(self, client: genai.Client, model: str = "gemini-3-flash-preview"):
        self._client = client
        self._model = model

    async def generate_answer(
        self,
        query: str,
        category: str,
        chunks: list[ChunkResult],
        is_onboarding: bool = False,
        conversation_history: list | None = None,
    ) -> tuple[str, list[int], list[str]]:
        """검색된 청크를 컨텍스트로 사용하여 RAG 답변, 인용 인덱스, 후속 질문을 반환한다."""
        if not chunks:
            return "관련 문서를 찾지 못했습니다. 다른 검색어로 시도해 주세요.", [], []

        context = self._build_context(chunks, is_onboarding=is_onboarding)
        cat_name = (
            ONBOARDING_CATEGORY_NAMES.get(category, category)
            if is_onboarding
            else CATEGORY_NAMES.get(category, category)
        )
        system_prompt = ONBOARDING_SYSTEM_PROMPT if is_onboarding else SYSTEM_PROMPT

        history_block = ""
        if conversation_history:
            lines = []
            for turn in conversation_history:
                role_label = "사용자" if turn.role == "user" else "봇"
                lines.append(f"{role_label}: {turn.content}")
            history_block = "이전 대화:\n" + "\n".join(lines) + "\n\n"

        user_prompt = f"""카테고리: {cat_name}
{history_block}현재 질문: {query}

컨텍스트:
---
{context}
---

위 컨텍스트를 기반으로 질문에 답변하세요."""

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            partial(
                self._client.models.generate_content,
                model=self._model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.3,
                    response_mime_type="application/json",
                    response_schema=_LLMResult,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            ),
        )

        result = response.parsed
        if result is None:
            logger.warning("structured output parsing failed, falling back to raw text")
            return response.text or "답변을 생성하지 못했습니다.", [], []
        return result.answer, result.cited_indices, result.follow_up_questions

    async def generate_checklist(
        self,
        category: str,
        chunks: list[ChunkResult],
    ) -> tuple[str, list[dict]]:
        """카테고리 온보딩 청크로부터 구조화된 학습 경로를 생성한다."""
        if not chunks:
            cat_name = ONBOARDING_CATEGORY_NAMES.get(category, category)
            return f"{cat_name} 온보딩 체크리스트", []

        context = self._build_context(chunks, is_onboarding=True)
        cat_name = ONBOARDING_CATEGORY_NAMES.get(category, category)

        user_prompt = f"""분야: {cat_name}

다음 온보딩 문서들을 분석하여 {cat_name} 팀 온보딩 학습 경로를 생성하세요.

컨텍스트:
---
{context}
---

위 컨텍스트를 기반으로 구조화된 학습 경로를 생성하세요."""

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            partial(
                self._client.models.generate_content,
                model=self._model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=CHECKLIST_SYSTEM_PROMPT,
                    temperature=0.3,
                    response_mime_type="application/json",
                    response_schema=_ChecklistResult,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            ),
        )

        result = response.parsed
        if result is None:
            logger.warning("checklist structured output parsing failed")
            return f"{cat_name} 온보딩 체크리스트", []
        steps = [
            {
                "step_number": s.step_number,
                "title": s.title,
                "description": s.description,
                "search_query": s.search_query,
            }
            for s in result.steps
        ]
        return result.title, steps

    async def reformulate_query(
        self,
        original_query: str,
        chunk_titles: list[str],
        category: str = "all",
    ) -> str:
        """검색 결과가 부족할 때 쿼리를 재구성한다. 실패 시 원본 쿼리를 반환."""
        context_hint = ""
        if chunk_titles:
            titles_str = ", ".join(chunk_titles[:5])
            context_hint = f"\n검색된 문서 제목들 (관련도 낮음): {titles_str}"

        user_prompt = (
            f"원래 질문: {original_query}\n"
            f"카테고리: {category}"
            f"{context_hint}\n\n"
            f"위 질문을 검색에 더 적합하게 재구성하세요."
        )

        loop = asyncio.get_running_loop()
        try:
            response = await loop.run_in_executor(
                None,
                partial(
                    self._client.models.generate_content,
                    model=self._model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=REFORMULATE_SYSTEM_PROMPT,
                        temperature=0.3,
                        response_mime_type="application/json",
                        response_schema=_ReformulateResult,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    ),
                ),
            )
            result = response.parsed
            if result and result.reformulated_query:
                logger.info(
                    "query reformulated: original=%r reformulated=%r reason=%r",
                    original_query,
                    result.reformulated_query,
                    result.reasoning,
                )
                return result.reformulated_query
        except Exception:
            logger.warning("query reformulation failed, using original query")
        return original_query

    async def decompose_query(self, query: str, max_sub_queries: int = 3) -> list[str]:
        """복잡한 질문을 하위 쿼리로 분해한다. 단순 질문이면 원본을 리스트로 반환."""
        user_prompt = f"다음 질문을 분석하세요:\n{query}"

        loop = asyncio.get_running_loop()
        try:
            response = await loop.run_in_executor(
                None,
                partial(
                    self._client.models.generate_content,
                    model=self._model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=DECOMPOSE_SYSTEM_PROMPT,
                        temperature=0.1,
                        response_mime_type="application/json",
                        response_schema=_DecomposeResult,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    ),
                ),
            )
            result = response.parsed
            if result and result.needs_decomposition and result.sub_queries:
                return result.sub_queries[:max_sub_queries]
        except Exception:
            logger.warning("query decomposition failed, using original query")
        return [query]

    def _build_context(self, chunks: list[ChunkResult], *, is_onboarding: bool = False) -> str:
        """청크 목록을 번호 매겨진 컨텍스트 문자열로 변환한다."""
        parent_limit = 3500 if is_onboarding else 1500
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
                    f"[참고: 전체 페이지]\n{chunk.parent_content[:parent_limit]}"
                )
            else:
                content = chunk.content
            parts.append(f"{header}\n{content}\n")
        return "\n".join(parts)
