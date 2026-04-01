"""Multi-turn 대화 맥락 유지 테스트."""

from unittest.mock import AsyncMock, patch

import pytest

from app.cache import ConversationCache, ConversationTurn
from app.models.response import SearchMetadata, SearchResponse
from app.services.slack_bot import SlackBotService


def test_conversation_cache_append_and_get() -> None:
    cache = ConversationCache(maxsize=10, ttl=60, max_turns=5)
    cache.append("C123", "ts1", "질문1", "답변1")

    history = cache.get("C123", "ts1")
    assert len(history) == 2
    assert history[0] == ConversationTurn(role="user", content="질문1")
    assert history[1] == ConversationTurn(role="assistant", content="답변1")


def test_conversation_cache_max_turns() -> None:
    cache = ConversationCache(maxsize=10, ttl=60, max_turns=2)
    cache.append("C1", "ts1", "q1", "a1")
    cache.append("C1", "ts1", "q2", "a2")
    cache.append("C1", "ts1", "q3", "a3")

    history = cache.get("C1", "ts1")
    # max_turns=2 → 최근 2쌍(4턴)만 유지
    assert len(history) == 4
    assert history[0].content == "q2"
    assert history[3].content == "a3"


def test_conversation_cache_different_threads() -> None:
    cache = ConversationCache(maxsize=10, ttl=60, max_turns=5)
    cache.append("C1", "ts1", "q1", "a1")
    cache.append("C1", "ts2", "q2", "a2")

    h1 = cache.get("C1", "ts1")
    h2 = cache.get("C1", "ts2")
    assert len(h1) == 2
    assert len(h2) == 2
    assert h1[0].content == "q1"
    assert h2[0].content == "q2"


def test_conversation_cache_empty_thread() -> None:
    cache = ConversationCache(maxsize=10, ttl=60)
    history = cache.get("C1", "no_such_thread")
    assert history == []


def test_conversation_cache_answer_truncated() -> None:
    cache = ConversationCache(maxsize=10, ttl=60)
    long_answer = "x" * 1000
    cache.append("C1", "ts1", "q", long_answer)
    history = cache.get("C1", "ts1")
    assert len(history[1].content) == 500


@pytest.fixture
def mock_orchestrator_with_response() -> AsyncMock:
    orch = AsyncMock()
    response = SearchResponse(
        answer="컨텍스트 기반 답변",
        sources=[],
        category="all",
        metadata=SearchMetadata(chunks_retrieved=3, latency_ms=250),
    )
    orch.multi_step_search.return_value = response
    return orch


async def test_slack_dm_multiturn(mock_orchestrator_with_response: AsyncMock) -> None:
    """DM 스레드에서 맥락이 유지되는지 검증."""
    conv_cache = ConversationCache(maxsize=10, ttl=60)

    with (
        patch("app.services.slack_bot.AsyncApp"),
        patch("app.services.slack_bot.AsyncSocketModeHandler"),
    ):
        bot = SlackBotService(
            bot_token="xoxb-test",
            app_token="xapp-test",
            orchestrator=mock_orchestrator_with_response,
            conversation_cache=conv_cache,
        )

    client = AsyncMock()

    # 첫 번째 메시지
    event1 = {
        "text": "SEO 업무 프로세스 알려줘",
        "channel_type": "im",
        "channel": "D123",
        "ts": "100.001",
    }
    await bot._handle_dm(event1, client)
    assert mock_orchestrator_with_response.multi_step_search.call_count == 1
    # conversation_history=None (첫 메시지이므로 이력 없음)
    first_call = mock_orchestrator_with_response.multi_step_search.call_args
    assert first_call.kwargs.get("conversation_history") is None

    # 이력 저장 확인
    history = conv_cache.get("D123", "100.001")
    assert len(history) == 2

    # 두 번째 메시지 (같은 스레드)
    event2 = {
        "text": "그 중에서 키워드 리서치 방법은?",
        "channel_type": "im",
        "channel": "D123",
        "thread_ts": "100.001",
        "ts": "100.002",
    }
    await bot._handle_dm(event2, client)
    second_call = mock_orchestrator_with_response.multi_step_search.call_args
    # 이전 이력이 전달되어야 함
    assert second_call.kwargs.get("conversation_history") is not None
    assert len(second_call.kwargs["conversation_history"]) == 2
