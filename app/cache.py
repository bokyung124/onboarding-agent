"""검색 결과 TTL 인메모리 캐시."""

import hashlib

from cachetools import TTLCache

from app.models.response import SearchResponse


class SearchCache:
    def __init__(self, maxsize: int = 500, ttl: int = 3600):
        self._cache: TTLCache[str, SearchResponse] = TTLCache(maxsize=maxsize, ttl=ttl)

    def _key(self, category: str, query: str) -> str:
        normalized = query.strip().lower()
        return hashlib.sha256(f"{category}:{normalized}".encode()).hexdigest()

    def get(self, category: str, query: str) -> SearchResponse | None:
        return self._cache.get(self._key(category, query))

    def set(self, category: str, query: str, response: SearchResponse) -> None:
        self._cache[self._key(category, query)] = response
