"""검색 결과 TTL 인메모리 캐시."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from cachetools import TTLCache

from app.models.response import SearchResponse

if TYPE_CHECKING:
    from app.models.request import SearchRequest


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
