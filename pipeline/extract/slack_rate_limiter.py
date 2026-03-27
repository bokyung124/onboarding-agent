import asyncio
import logging

from slack_sdk.errors import SlackApiError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Slack API Tier 2/3: 보수적으로 3 동시 요청, ~50 req/min 미만
_semaphore = asyncio.Semaphore(3)


def _is_retryable(exception: BaseException) -> bool:
    """Rate limit(ratelimited) 에러만 재시도한다."""
    if isinstance(exception, SlackApiError):
        return exception.response.get("error") == "ratelimited"
    return False


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(5),
    before_sleep=lambda retry_state: logger.warning(
        "Retrying Slack API call (attempt %d): %s",
        retry_state.attempt_number,
        retry_state.outcome.exception(),
    ),
)
async def slack_rate_limited_call(method, **kwargs):
    """Slack API 호출을 rate limit에 맞춰 실행한다."""
    async with _semaphore:
        result = await method(**kwargs)
        await asyncio.sleep(1.2)  # ~50 req/min 안전 마진
        return result
