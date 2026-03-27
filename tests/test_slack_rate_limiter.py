"""Slack Rate Limiter 테스트."""

from unittest.mock import AsyncMock

import pytest
from slack_sdk.errors import SlackApiError

from pipeline.extract.slack_rate_limiter import slack_rate_limited_call


@pytest.mark.asyncio
async def test_rate_limited_call_success():
    """정상 호출이 결과를 반환해야 한다."""
    mock_method = AsyncMock(return_value={"ok": True, "messages": []})
    result = await slack_rate_limited_call(mock_method, channel="C123")
    assert result["ok"] is True
    mock_method.assert_called_once_with(channel="C123")


@pytest.mark.asyncio
async def test_rate_limited_call_retries_on_ratelimited():
    """ratelimited 에러 시 재시도해야 한다."""
    error_response = {"ok": False, "error": "ratelimited"}
    error = SlackApiError("ratelimited", response=error_response)

    mock_method = AsyncMock(
        side_effect=[error, {"ok": True, "messages": []}]
    )
    result = await slack_rate_limited_call(mock_method, channel="C123")
    assert result["ok"] is True
    assert mock_method.call_count == 2


@pytest.mark.asyncio
async def test_rate_limited_call_does_not_retry_on_other_errors():
    """ratelimited가 아닌 에러는 재시도하지 않아야 한다."""
    error_response = {"ok": False, "error": "channel_not_found"}
    error = SlackApiError("channel_not_found", response=error_response)

    mock_method = AsyncMock(side_effect=error)
    with pytest.raises(SlackApiError):
        await slack_rate_limited_call(mock_method, channel="C123")
    assert mock_method.call_count == 1
