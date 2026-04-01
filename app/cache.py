"""검색 결과 TTL 인메모리 캐시."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from cachetools import TTLCache
from pydantic import BaseModel

from app.models.response import ChecklistResponse, SearchResponse

if TYPE_CHECKING:
    from app.models.request import SearchRequest


class ConversationTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class SearchCache:
    def __init__(self, maxsize: int = 500, ttl: int = 3600):
        self._cache: TTLCache[str, SearchResponse] = TTLCache(maxsize=maxsize, ttl=ttl)

    def _key(self, request: SearchRequest) -> str:
        parts = (
            f"{request.category}:{request.query.strip().lower()}"
            f":{request.client_name or ''}:{request.tags or ''}"
        )
        return hashlib.sha256(parts.encode()).hexdigest()

    def get(self, request: SearchRequest) -> SearchResponse | None:
        return self._cache.get(self._key(request))

    def set(self, request: SearchRequest, response: SearchResponse) -> None:
        self._cache[self._key(request)] = response

    def clear(self) -> int:
        """캐시를 전체 초기화하고 삭제된 항목 수를 반환한다."""
        size = len(self._cache)
        self._cache.clear()
        return size


class ChecklistCache:
    """카테고리별 체크리스트 TTL 캐시. 키 = category slug."""

    def __init__(self, maxsize: int = 20, ttl: int = 86400):
        self._cache: TTLCache[str, ChecklistResponse] = TTLCache(maxsize=maxsize, ttl=ttl)

    def get(self, category: str) -> ChecklistResponse | None:
        return self._cache.get(f"checklist:{category}")

    def set(self, category: str, response: ChecklistResponse) -> None:
        self._cache[f"checklist:{category}"] = response

    def clear(self) -> int:
        """캐시를 전체 초기화하고 삭제된 항목 수를 반환한다."""
        size = len(self._cache)
        self._cache.clear()
        return size


class ConversationCache:
    """Slack 스레드별 대화 이력 TTL 캐시. 키 = channel:thread_ts."""

    def __init__(self, maxsize: int = 200, ttl: int = 3600, max_turns: int = 5):
        self._cache: TTLCache[str, list[ConversationTurn]] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._max_turns = max_turns

    def _key(self, channel: str, thread_ts: str) -> str:
        return f"conv:{channel}:{thread_ts}"

    def get(self, channel: str, thread_ts: str) -> list[ConversationTurn]:
        return list(self._cache.get(self._key(channel, thread_ts), []))

    def append(self, channel: str, thread_ts: str, query: str, answer: str) -> None:
        key = self._key(channel, thread_ts)
        history = list(self._cache.get(key, []))
        history.append(ConversationTurn(role="user", content=query))
        history.append(ConversationTurn(role="assistant", content=answer[:500]))
        if len(history) > self._max_turns * 2:
            history = history[-(self._max_turns * 2) :]
        self._cache[key] = history

    def clear(self) -> int:
        size = len(self._cache)
        self._cache.clear()
        return size
