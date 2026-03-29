"""Notion API에서 전체 워크스페이스를 크롤링하여 페이지, 블록, 데이터베이스를 추출한다."""

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Protocol

from notion_client import AsyncClient

from pipeline.extract.rate_limiter import rate_limited_call


class BatchSink(Protocol):
    """배치 단위로 추출 결과를 외부 저장소에 flush하는 인터페이스."""

    async def flush(
        self,
        pages: list[dict],
        blocks: list[dict],
        databases: list[dict],
        comments: list[dict],
    ) -> None: ...


logger = logging.getLogger(__name__)


# ── Rich Text → Plain Text ────────────────────────────────────────────────


def _rich_text_to_plain(rich_text_array: list[dict]) -> str:
    """Notion rich_text 배열을 plain text로 변환한다."""
    return "".join(rt.get("plain_text", "") for rt in rich_text_array)


def _rich_text_to_markdown(rich_text_array: list[dict]) -> str:
    """Notion rich_text 배열을 markdown으로 변환한다."""
    parts: list[str] = []
    for rt in rich_text_array:
        text = rt.get("plain_text", "")
        annotations = rt.get("annotations", {})
        if annotations.get("bold"):
            text = f"**{text}**"
        if annotations.get("italic"):
            text = f"*{text}*"
        if annotations.get("strikethrough"):
            text = f"~~{text}~~"
        if annotations.get("code"):
            text = f"`{text}`"
        href = rt.get("href")
        if href:
            text = f"[{text}]({href})"
        parts.append(text)
    return "".join(parts)


# ── Block → Text ──────────────────────────────────────────────────────────


def extract_block_text(block: dict) -> tuple[str, str]:
    """블록에서 (plain_text, markdown_text)를 추출한다."""
    block_type = block.get("type", "")
    block_data = block.get(block_type, {})

    # 대부분의 블록은 rich_text 필드를 가진다
    rich_text = block_data.get("rich_text", [])
    if not rich_text:
        # caption이 있는 블록 (image, bookmark 등)
        rich_text = block_data.get("caption", [])

    plain = _rich_text_to_plain(rich_text)
    md = _rich_text_to_markdown(rich_text)

    # 블록 타입별 마크다운 포맷팅
    if block_type == "heading_1":
        md = f"# {md}"
    elif block_type == "heading_2":
        md = f"## {md}"
    elif block_type == "heading_3":
        md = f"### {md}"
    elif block_type == "bulleted_list_item":
        md = f"- {md}"
    elif block_type == "numbered_list_item":
        md = f"1. {md}"
    elif block_type == "quote":
        md = f"> {md}"
    elif block_type == "callout":
        icon = block_data.get("icon", {})
        emoji = icon.get("emoji", "") if icon else ""
        md = f"> {emoji} {md}"
    elif block_type == "code":
        language = block_data.get("language", "")
        md = f"```{language}\n{plain}\n```"
    elif block_type == "bookmark":
        url = block_data.get("url", "")
        md = f"[{md or url}]({url})" if url else md
    elif block_type == "image":
        url = ""
        image_data = block_data
        if image_data.get("type") == "external":
            url = image_data.get("external", {}).get("url", "")
        elif image_data.get("type") == "file":
            url = image_data.get("file", {}).get("url", "")
        md = f"![{md}]({url})"
    elif block_type == "divider":
        plain = "---"
        md = "---"

    return plain, md


# ── Property 추출 ─────────────────────────────────────────────────────────

PROPERTY_EXTRACTORS: dict[str, callable] = {
    "title": lambda p: _rich_text_to_plain(p.get("title", [])),
    "rich_text": lambda p: _rich_text_to_plain(p.get("rich_text", [])),
    "select": lambda p: p["select"]["name"] if p.get("select") else None,
    "multi_select": lambda p: [o["name"] for o in p.get("multi_select", [])],
    "date": lambda p: p["date"]["start"] if p.get("date") else None,
    "checkbox": lambda p: p.get("checkbox"),
    "number": lambda p: p.get("number"),
    "url": lambda p: p.get("url"),
    "email": lambda p: p.get("email"),
    "phone_number": lambda p: p.get("phone_number"),
    "status": lambda p: p["status"]["name"] if p.get("status") else None,
    "people": lambda p: [u.get("name", u["id"]) for u in p.get("people", [])],
    "relation": lambda p: [r["id"] for r in p.get("relation", [])],
    "created_time": lambda p: p.get("created_time"),
    "last_edited_time": lambda p: p.get("last_edited_time"),
}


def extract_page_title(page: dict) -> str:
    """페이지 object에서 제목을 추출한다."""
    properties = page.get("properties", {})
    for prop in properties.values():
        if prop.get("type") == "title":
            return _rich_text_to_plain(prop.get("title", []))
    return ""


# ── Notion Extractor ──────────────────────────────────────────────────────


class NotionExtractor:
    """Notion API에서 페이지, 블록, 데이터베이스를 BFS로 추출한다."""

    def __init__(self, api_key: str, root_page_id: str | None = None):
        self._client = AsyncClient(auth=api_key)
        self._root_page_id = root_page_id
        self._visited_pages: set[str] = set()
        self._visited_databases: set[str] = set()

    async def close(self) -> None:
        await self._client.aclose()

    # ── 전체 크롤링 ──

    async def crawl_all(
        self,
        since: str | None = None,
        sink: BatchSink | None = None,
        batch_size: int = 100,
    ) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
        """전체 워크스페이스를 크롤링한다.

        Args:
            since: ISO 8601 타임스탬프. 지정하면 이후 수정된 페이지만 추출.
            sink: 배치 flush 대상. 지정하면 batch_size마다 flush 후 버퍼 클리어.
            batch_size: sink flush 단위 (페이지 수 기준). 기본 100.

        Returns:
            sink 미지정 시 (pages, blocks, databases, comments) 튜플.
            sink 지정 시 빈 리스트 튜플 (데이터는 sink로 flush됨).
        """
        all_pages: list[dict] = []
        all_blocks: list[dict] = []
        all_databases: list[dict] = []
        all_comments: list[dict] = []

        # 시작 페이지 수집
        seed_page_ids = await self._get_seed_pages(since)
        logger.info("Seed pages: %d", len(seed_page_ids))

        # BFS 순회
        queue: deque[str] = deque(seed_page_ids)
        extracted_at = datetime.now(timezone.utc).isoformat()

        while queue:
            page_id = queue.popleft()
            if page_id in self._visited_pages:
                continue
            self._visited_pages.add(page_id)

            # 페이지 메타데이터 가져오기
            try:
                page = await rate_limited_call(self._client.pages.retrieve, page_id=page_id)
            except Exception:
                logger.warning("Failed to retrieve page %s", page_id, exc_info=True)
                continue

            # 증분 필터: since 이전 수정된 페이지 스킵
            if since and page.get("last_edited_time", "") < since:
                continue

            page_record = {
                "page_id": page["id"],
                "parent_type": page.get("parent", {}).get("type"),
                "parent_id": (
                    page.get("parent", {}).get("page_id")
                    or page.get("parent", {}).get("database_id")
                ),
                "title": extract_page_title(page),
                "url": page.get("url", ""),
                "created_time": page.get("created_time"),
                "last_edited_time": page.get("last_edited_time"),
                "is_archived": page.get("archived", False),
                "properties_json": page.get("properties", {}),
                "_extracted_at": extracted_at,
            }
            all_pages.append(page_record)

            # 블록 추출 (child_page, child_database를 큐에 추가)
            blocks = await self._extract_page_blocks(page_id, extracted_at)
            for block in blocks:
                all_blocks.append(block)
                if block["block_type"] == "child_page" and block.get("child_page_id"):
                    queue.append(block["child_page_id"])
                elif block["block_type"] == "child_database" and block.get("child_database_id"):
                    db_id = block["child_database_id"]
                    if db_id not in self._visited_databases:
                        db_record = await self._extract_database(db_id, extracted_at)
                        if db_record:
                            all_databases.append(db_record)
                        # 데이터베이스 안의 페이지들을 BFS 큐에 추가
                        db_page_ids = await self._query_database_pages(db_id)
                        queue.extend(db_page_ids)

            # 댓글 추출 (페이지 레벨 + 블록별 인라인)
            block_ids = [b["block_id"] for b in blocks]
            comments = await self._extract_page_comments(page_id, block_ids, extracted_at)
            all_comments.extend(comments)

            logger.info(
                "Extracted page: %s (%d blocks, %d comments)",
                page_record["title"],
                len(blocks),
                len(comments),
            )

            # 배치 flush
            if sink and len(all_pages) >= batch_size:
                await sink.flush(
                    list(all_pages),
                    list(all_blocks),
                    list(all_databases),
                    list(all_comments),
                )
                all_pages.clear()
                all_blocks.clear()
                all_databases.clear()
                all_comments.clear()

        # 잔여분 flush
        if sink and (all_pages or all_blocks or all_databases or all_comments):
            await sink.flush(
                list(all_pages),
                list(all_blocks),
                list(all_databases),
                list(all_comments),
            )
            all_pages.clear()
            all_blocks.clear()
            all_databases.clear()
            all_comments.clear()

        logger.info(
            "Crawl complete: %d pages visited",
            len(self._visited_pages),
        )
        return all_pages, all_blocks, all_databases, all_comments

    # ── 시드 페이지 수집 ──

    async def _get_seed_pages(self, since: str | None) -> list[str]:
        """크롤링 시작점이 될 페이지 ID 목록을 가져온다."""
        if self._root_page_id:
            return [self._root_page_id]

        # 루트 페이지가 없으면 Search API로 전체 페이지 검색
        page_ids: list[str] = []
        cursor = None
        while True:
            resp = await rate_limited_call(
                self._client.search,
                filter={"property": "object", "value": "page"},
                sort={"direction": "descending", "timestamp": "last_edited_time"},
                start_cursor=cursor,
            )
            for page in resp["results"]:
                if since and page.get("last_edited_time", "") < since:
                    return page_ids
                page_ids.append(page["id"])
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return page_ids

    # ── 블록 추출 ──

    async def _extract_page_blocks(
        self, page_id: str, extracted_at: str, parent_block_id: str | None = None
    ) -> list[dict]:
        """페이지(또는 블록)의 자식 블록을 페이지네이션으로 모두 가져온다."""
        blocks: list[dict] = []
        cursor = None
        block_order = 0

        while True:
            try:
                resp = await rate_limited_call(
                    self._client.blocks.children.list,
                    block_id=parent_block_id or page_id,
                    start_cursor=cursor,
                    page_size=100,
                )
            except Exception:
                logger.warning(
                    "Failed to list blocks for %s", parent_block_id or page_id, exc_info=True
                )
                break

            for block in resp["results"]:
                plain_text, markdown_text = extract_block_text(block)
                block_type = block.get("type", "")

                record = {
                    "block_id": block["id"],
                    "page_id": page_id,
                    "parent_block_id": parent_block_id,
                    "block_type": block_type,
                    "block_order": block_order,
                    "has_children": block.get("has_children", False),
                    "rich_text_plain": plain_text,
                    "rich_text_markdown": markdown_text,
                    "last_edited_time": block.get("last_edited_time"),
                    "_extracted_at": extracted_at,
                }

                # child_page, child_database 참조 ID 추가
                if block_type == "child_page":
                    record["child_page_id"] = block["id"]
                elif block_type == "child_database":
                    record["child_database_id"] = block["id"]
                else:
                    record["child_page_id"] = None
                    record["child_database_id"] = None

                # 빈 텍스트 블록은 저장하지 않되, 자식이 있는 블록은 유지
                if not plain_text and not markdown_text and not block.get("has_children"):
                    continue

                blocks.append(record)
                block_order += 1

                # 중첩 블록 재귀 (toggle, column 등)
                if block.get("has_children") and block_type not in (
                    "child_page",
                    "child_database",
                ):
                    child_blocks = await self._extract_page_blocks(
                        page_id, extracted_at, parent_block_id=block["id"]
                    )
                    blocks.extend(child_blocks)

            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")

        return blocks

    # ── 댓글 추출 ──

    async def _extract_page_comments(
        self, page_id: str, block_ids: list[str], extracted_at: str
    ) -> list[dict]:
        """페이지 레벨 + 블록별 인라인 댓글을 추출한다."""
        all_comments: list[dict] = []

        # 페이지 레벨 댓글 + 각 블록의 인라인 댓글
        targets = [page_id] + block_ids
        for target_id in targets:
            is_page = target_id == page_id
            cursor = None
            while True:
                try:
                    resp = await rate_limited_call(
                        self._client.comments.list,
                        block_id=target_id,
                        start_cursor=cursor,
                        page_size=100,
                    )
                except Exception:
                    logger.warning(
                        "Failed to list comments for %s",
                        target_id,
                        exc_info=True,
                    )
                    break

                for comment in resp["results"]:
                    rich_text = comment.get("rich_text", [])
                    all_comments.append(
                        {
                            "comment_id": comment["id"],
                            "page_id": page_id,
                            "parent_block_id": None if is_page else target_id,
                            "discussion_id": comment.get("discussion_id", ""),
                            "created_by_id": comment.get("created_by", {}).get("id", ""),
                            "content_plain": _rich_text_to_plain(rich_text),
                            "content_markdown": _rich_text_to_markdown(rich_text),
                            "created_time": comment.get("created_time"),
                            "last_edited_time": comment.get("last_edited_time"),
                            "_extracted_at": extracted_at,
                        }
                    )

                if not resp.get("has_more"):
                    break
                cursor = resp.get("next_cursor")

        return all_comments

    # ── 데이터베이스 페이지 조회 ──

    async def _query_database_pages(self, database_id: str) -> list[str]:
        """데이터베이스 안의 모든 페이지 ID를 조회한다."""
        page_ids: list[str] = []
        cursor = None
        while True:
            try:
                body: dict = {"page_size": 100}
                if cursor:
                    body["start_cursor"] = cursor
                resp = await rate_limited_call(
                    self._client.request,
                    path=f"/databases/{database_id}/query",
                    method="POST",
                    body=body,
                )
            except Exception:
                logger.warning("Failed to query database %s", database_id, exc_info=True)
                break

            for page in resp["results"]:
                page_ids.append(page["id"])

            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")

        logger.info("Database %s contains %d pages", database_id, len(page_ids))
        return page_ids

    # ── 데이터베이스 추출 ──

    async def _extract_database(self, database_id: str, extracted_at: str) -> dict | None:
        """데이터베이스 메타데이터를 추출한다."""
        if database_id in self._visited_databases:
            return None
        self._visited_databases.add(database_id)

        try:
            db = await rate_limited_call(self._client.databases.retrieve, database_id=database_id)
        except Exception:
            logger.warning("Failed to retrieve database %s", database_id, exc_info=True)
            return None

        title = _rich_text_to_plain(db.get("title", []))
        return {
            "database_id": db["id"],
            "parent_id": (
                db.get("parent", {}).get("page_id") or db.get("parent", {}).get("database_id")
            ),
            "title": title,
            "description": _rich_text_to_plain(db.get("description", [])),
            "schema_json": {
                name: {"type": prop.get("type"), "name": name}
                for name, prop in db.get("properties", {}).items()
            },
            "is_inline": db.get("is_inline", False),
            "_extracted_at": extracted_at,
        }
