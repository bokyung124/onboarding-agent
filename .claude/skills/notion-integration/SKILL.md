---
name: notion-integration
description: 노션 API 연동 패턴. 노션 API와 상호작용하는 코드를 작성하거나 디버깅할 때 사용. 전체 페이지 순회, 검색, 블록 읽기, 텍스트 추출 포함.
---

# Notion API Integration

## SDK Setup

```python
from notion_client import AsyncClient
import os

notion = AsyncClient(auth=os.environ["NOTION_API_KEY"])
```

## 전체 페이지 순회 (핵심 패턴)

분야별·고객사별 페이지를 루트부터 재귀 탐색:

```python
async def crawl_all_pages(root_page_id: str) -> list[dict]:
    """루트 페이지부터 모든 하위 페이지를 재귀적으로 탐색"""
    pages = []

    async def _crawl(page_id: str, depth: int = 0):
        blocks = await get_page_blocks(page_id)
        for block in blocks:
            if block["type"] == "child_page":
                child_id = block["id"]
                page_info = await notion.pages.retrieve(page_id=child_id)
                pages.append({
                    "id": child_id,
                    "title": extract_title(page_info),
                    "depth": depth,
                    "parent_id": page_id,
                })
                await _crawl(child_id, depth + 1)

    await _crawl(root_page_id)
    return pages
```

## 페이지 블록 읽기 (페이지네이션 필수)

```python
async def get_page_blocks(page_id: str) -> list[dict]:
    blocks = []
    cursor = None
    while True:
        resp = await notion.blocks.children.list(block_id=page_id, start_cursor=cursor)
        blocks.extend(resp["results"])
        if not resp["has_more"]:
            break
        cursor = resp["next_cursor"]
    return blocks
```

## 텍스트 추출

```python
def extract_text(blocks: list[dict]) -> str:
    parts = []
    for block in blocks:
        btype = block["type"]
        if btype in ("paragraph", "heading_1", "heading_2", "heading_3",
                     "bulleted_list_item", "numbered_list_item", "toggle"):
            rich_texts = block[btype].get("rich_text", [])
            parts.append("".join(rt["plain_text"] for rt in rich_texts))
    return "\n".join(parts)
```

## 검색 API

```python
async def search_pages(query: str) -> list[dict]:
    response = await notion.search(
        query=query,
        filter={"property": "object", "value": "page"},
    )
    return response["results"]
```

## 중요 제약사항

- Rate limit: 초당 3 요청. 반드시 exponential backoff 재시도 구현.
- 블록 목록 페이지네이션: 항상 처리 (기본 100개 단위).
- 검색 API는 eventually consistent — 새 페이지는 수초 후에 나타남.
- 검색 API는 parent 필터 미지원 → 클라이언트에서 필터링 필요.
- 전체 크롤링은 비용이 크므로 결과를 캐싱하고 주기적으로 갱신.

## 페이지 URL 생성

```python
def page_id_to_url(page_id: str) -> str:
    return f"https://www.notion.so/{page_id.replace('-', '')}"
```

상세 API 패턴은 `references/notion-api-patterns.md` 참조.
