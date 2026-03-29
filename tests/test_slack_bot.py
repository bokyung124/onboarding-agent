"""Slack Bot 서비스 테스트."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.response import SearchMetadata, SearchResponse, Source
from app.services.slack_bot import SlackBotService, _strip_mentions
from app.services.slack_formatter import fallback_text, format_answer_blocks

# --- _strip_mentions ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("<@U12345> 질문입니다", "질문입니다"),
        ("<@U12345>  여러 공백  ", "여러 공백"),
        ("<@UABC> <@UDEF> 두 멘션", "두 멘션"),
        ("멘션 없는 텍스트", "멘션 없는 텍스트"),
        ("<@U12345>", ""),
    ],
)
def test_strip_mentions(text: str, expected: str) -> None:
    assert _strip_mentions(text) == expected


# --- format_answer_blocks ---


@pytest.fixture
def sample_response() -> SearchResponse:
    return SearchResponse(
        answer="답변입니다.",
        sources=[
            Source(
                title="가이드",
                url="https://notion.so/page-1",
                breadcrumb="Tech > 가이드",
                page_id="page-1",
                source_type="notion",
            ),
        ],
        category="all",
        metadata=SearchMetadata(chunks_retrieved=3, latency_ms=500),
    )


def test_format_answer_blocks_structure(sample_response: SearchResponse) -> None:
    blocks = format_answer_blocks(sample_response)
    assert blocks[0]["type"] == "section"
    assert "답변입니다." in blocks[0]["text"]["text"]
    assert blocks[1]["type"] == "divider"
    assert blocks[2]["type"] == "context"
    assert "가이드" in blocks[2]["elements"][0]["text"]
    assert blocks[3]["type"] == "context"
    assert "3개" in blocks[3]["elements"][0]["text"]


def test_format_answer_blocks_no_sources() -> None:
    response = SearchResponse(
        answer="답변",
        sources=[],
        category="all",
        metadata=SearchMetadata(chunks_retrieved=0, latency_ms=100),
    )
    blocks = format_answer_blocks(response)
    assert len(blocks) == 2  # section + metadata context only
    assert blocks[0]["type"] == "section"
    assert blocks[1]["type"] == "context"


def test_fallback_text(sample_response: SearchResponse) -> None:
    assert fallback_text(sample_response) == "답변입니다."


# --- SlackBotService handlers ---


@pytest.fixture
def mock_orchestrator() -> AsyncMock:
    orch = AsyncMock()
    orch.search.return_value = SearchResponse(
        answer="테스트 답변",
        sources=[],
        category="all",
        metadata=SearchMetadata(chunks_retrieved=1, latency_ms=200),
    )
    return orch


@pytest.fixture
def mock_cache() -> MagicMock:
    cache = MagicMock()
    cache.get.return_value = None
    return cache


@pytest.fixture
def bot_service(mock_orchestrator: AsyncMock, mock_cache: MagicMock) -> SlackBotService:
    with (
        patch("app.services.slack_bot.AsyncApp"),
        patch("app.services.slack_bot.AsyncSocketModeHandler"),
    ):
        return SlackBotService(
            bot_token="xoxb-test",
            app_token="xapp-test",
            orchestrator=mock_orchestrator,
            cache=mock_cache,
        )


async def test_handle_mention(bot_service: SlackBotService, mock_orchestrator: AsyncMock) -> None:
    say = AsyncMock()
    event = {"text": "<@UBOT> 온보딩 절차 알려줘", "channel": "C123"}
    await bot_service._handle_mention(event, say)
    mock_orchestrator.search.assert_called_once()
    say.assert_called_once()


async def test_handle_dm(bot_service: SlackBotService, mock_orchestrator: AsyncMock) -> None:
    say = AsyncMock()
    event = {"text": "온보딩 절차 알려줘", "channel_type": "im", "channel": "D123"}
    await bot_service._handle_dm(event, say)
    mock_orchestrator.search.assert_called_once()
    say.assert_called_once()


async def test_handle_dm_ignores_non_im(
    bot_service: SlackBotService, mock_orchestrator: AsyncMock
) -> None:
    say = AsyncMock()
    event = {"text": "일반 채널 메시지", "channel_type": "channel", "channel": "C123"}
    await bot_service._handle_dm(event, say)
    mock_orchestrator.search.assert_not_called()
    say.assert_not_called()


async def test_handle_dm_ignores_bot_messages(
    bot_service: SlackBotService, mock_orchestrator: AsyncMock
) -> None:
    say = AsyncMock()
    event = {"text": "봇 메시지", "channel_type": "im", "bot_id": "B123"}
    await bot_service._handle_dm(event, say)
    mock_orchestrator.search.assert_not_called()
    say.assert_not_called()


async def test_empty_query_replies_help(
    bot_service: SlackBotService, mock_orchestrator: AsyncMock
) -> None:
    say = AsyncMock()
    event = {"text": "<@UBOT>", "channel": "C123"}
    await bot_service._handle_mention(event, say)
    say.assert_called_once_with("질문을 입력해 주세요.")
    mock_orchestrator.search.assert_not_called()


async def test_cache_hit_skips_orchestrator(
    bot_service: SlackBotService,
    mock_orchestrator: AsyncMock,
    mock_cache: MagicMock,
) -> None:
    cached_response = SearchResponse(
        answer="캐시된 답변",
        sources=[],
        category="all",
        metadata=SearchMetadata(chunks_retrieved=2, latency_ms=100),
    )
    mock_cache.get.return_value = cached_response

    say = AsyncMock()
    event = {"text": "<@UBOT> 캐시 테스트", "channel": "C123"}
    await bot_service._handle_mention(event, say)

    mock_orchestrator.search.assert_not_called()
    say.assert_called_once()
