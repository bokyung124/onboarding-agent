import asyncio
import logging

from notion_client import APIResponseError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Notion API: 3 requests/sec
_semaphore = asyncio.Semaphore(3)


def _is_retryable(exception: BaseException) -> bool:
    """Rate limit(429) 또는 서버 에러(5xx)만 재시도한다."""
    if isinstance(exception, APIResponseError):
        return exception.status >= 429
    return False


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    stop=stop_after_attempt(5),
    before_sleep=lambda retry_state: logger.warning(
        "Retrying Notion API call (attempt %d): %s",
        retry_state.attempt_number,
        retry_state.outcome.exception(),
    ),
)
async def rate_limited_call(fn, **kwargs):
    """Notion API 호출을 rate limit(3 req/sec)에 맞춰 실행한다."""
    async with _semaphore:
        result = await fn(**kwargs)
        await asyncio.sleep(0.35)  # 3 req/sec 안전 마진
        return result
