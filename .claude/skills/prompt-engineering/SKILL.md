---
name: prompt-engineering
description: Gemini API 기반 RAG 프롬프트 설계 가이드. 노션 컨텍스트로 답변을 생성하는 프롬프트를 설계하거나 수정할 때 사용.
---

# Prompt Engineering — Gemini API RAG

## Gemini SDK Setup

```python
from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

response = client.models.generate_content(
    model="gemini-3-flash-preview",
    contents=prompt,
)
answer = response.text
```

## RAG 흐름

1. 노션에서 관련 페이지 컨텐츠 검색/추출
2. 컨텍스트 + 질문으로 프롬프트 구성
3. Gemini API로 답변 생성
4. 답변에 출처(Source) 매핑

## System Prompt 템플릿

```
당신은 사내 온보딩 어시스턴트입니다.
제공된 노션 문서 컨텍스트만을 사용하여 질문에 답변합니다.

규칙:
- 제공된 컨텍스트에 있는 정보만 사용하세요. 정보가 부족하면 명시적으로 말하세요.
- 인라인 인용 [출처 N] 표기를 사용하세요.
- 답변은 간결하고 실행 가능하게. 여러 단계 프로세스는 불릿 포인트로.
- 여러 페이지가 같은 주제를 다루면 종합하세요.
- 정보를 만들어내지 마세요. 온보딩 정보의 정확성이 중요합니다.
- 신입 직원에게 적합한 친절하고 전문적인 톤을 사용하세요.
```

## User Prompt 템플릿

```
분야: {department}
질문: {query}

컨텍스트 (노션에서 검색됨):
---
[출처 1: {page_title_1}]
{page_content_1}

[출처 2: {page_title_2}]
{page_content_2}
---

위 컨텍스트를 사용하여 질문에 답변하세요. [출처 N]으로 인용하세요.
```

## 청킹 전략

- 페이지 컨텐츠를 ~500 토큰 단위, 50 토큰 오버랩으로 분할
- 헤딩 계층 유지: 각 청크에 부모 헤딩 포함
- 질문과의 관련도로 청크 랭킹 (BM25 또는 코사인 유사도)
- 상위 5~8개 청크를 프롬프트 컨텍스트에 포함

## 응답 포맷

```json
{
  "answer": "개발 환경을 설정하려면 Docker를 설치하고 [출처 1] 셋업 스크립트를 실행하세요 [출처 2].",
  "sources": [
    {"title": "개발 환경 가이드", "url": "https://notion.so/...", "block_id": "abc123"},
    {"title": "엔지니어링 온보딩", "url": "https://notion.so/...", "block_id": "def456"}
  ]
}
```

## 답변 품질 평가 기준

- **충실성**: 컨텍스트의 정보만 사용했는가?
- **관련성**: 실제 질문에 답변했는가?
- **완전성**: 관련 컨텍스트를 모두 활용했는가?
- **인용 정확성**: 인용이 올바른 출처를 가리키는가?
