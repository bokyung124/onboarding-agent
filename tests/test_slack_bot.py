"""Slack Bot 서비스 테스트."""

from unittest.mock import AsyncMock, patch

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
    # 후속 질문 없으면 바로 metadata context
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


def test_format_answer_blocks_with_follow_ups() -> None:
    response = SearchResponse(
        answer="SEO 온보딩 절차입니다.",
        sources=[
            Source(
                title="SEO 가이드",
                url="https://notion.so/seo",
                breadcrumb="SEO",
                page_id="seo-1",
                source_type="notion",
            ),
        ],
        category="seo",
        metadata=SearchMetadata(chunks_retrieved=2, latency_ms=300),
        follow_up_questions=["GA4 설정 방법은?", "키워드 리서치 도구는?"],
    )
    blocks = format_answer_blocks(response)
    # section, divider, sources context, divider, follow-up context, actions, metadata context
    action_blocks = [b for b in blocks if b["type"] == "actions"]
    assert len(action_blocks) == 1
    buttons = action_blocks[0]["elements"]
    assert len(buttons) == 2
    assert buttons[0]["text"]["text"] == "GA4 설정 방법은?"
    assert buttons[0]["action_id"] == "follow_up_0"
    assert buttons[1]["action_id"] == "follow_up_1"


def test_format_answer_blocks_follow_ups_with_onboarding_flag() -> None:
    response = SearchResponse(
        answer="답변",
        sources=[],
        category="seo",
        metadata=SearchMetadata(chunks_retrieved=1, latency_ms=100),
        follow_up_questions=["후속 질문"],
    )
    blocks = format_answer_blocks(response, is_onboarding=True)
    action_blocks = [b for b in blocks if b["type"] == "actions"]
    assert len(action_blocks) == 1
    import json

    payload = json.loads(action_blocks[0]["elements"][0]["value"])
    assert payload["is_onboarding"] is True
    assert payload["query"] == "후속 질문"
    assert payload["category"] == "seo"


def test_fallback_text(sample_response: SearchResponse) -> None:
    assert fallback_text(sample_response) == "답변입니다."


# --- SlackBotService handlers ---


@pytest.fixture
def mock_orchestrator() -> AsyncMock:
    orch = AsyncMock()
    default_response = SearchResponse(
        answer="테스트 답변",
        sources=[],
        category="all",
        metadata=SearchMetadata(chunks_retrieved=1, latency_ms=200),
    )
    orch.search.return_value = default_response
    orch.multi_step_search.return_value = default_response
    return orch


@pytest.fixture
def bot_service(mock_orchestrator: AsyncMock) -> SlackBotService:
    with (
        patch("app.services.slack_bot.AsyncApp"),
        patch("app.services.slack_bot.AsyncSocketModeHandler"),
    ):
        return SlackBotService(
            bot_token="xoxb-test",
            app_token="xapp-test",
            orchestrator=mock_orchestrator,
        )


async def test_handle_mention(bot_service: SlackBotService, mock_orchestrator: AsyncMock) -> None:
    say = AsyncMock()
    event = {"text": "<@UBOT> 온보딩 절차 알려줘", "channel": "C123"}
    await bot_service._handle_mention(event, say)
    mock_orchestrator.multi_step_search.assert_called_once()
    say.assert_called_once()


async def test_handle_dm(bot_service: SlackBotService, mock_orchestrator: AsyncMock) -> None:
    client = AsyncMock()
    event = {"text": "온보딩 절차 알려줘", "channel_type": "im", "channel": "D123", "ts": "123"}
    await bot_service._handle_dm(event, client)
    mock_orchestrator.multi_step_search.assert_called_once()
    client.chat_postMessage.assert_called_once()


async def test_handle_dm_ignores_non_im(
    bot_service: SlackBotService, mock_orchestrator: AsyncMock
) -> None:
    client = AsyncMock()
    event = {"text": "일반 채널 메시지", "channel_type": "channel", "channel": "C123"}
    await bot_service._handle_dm(event, client)
    mock_orchestrator.search.assert_not_called()
    client.chat_postMessage.assert_not_called()


async def test_handle_dm_ignores_bot_messages(
    bot_service: SlackBotService, mock_orchestrator: AsyncMock
) -> None:
    client = AsyncMock()
    event = {"text": "봇 메시지", "channel_type": "im", "bot_id": "B123"}
    await bot_service._handle_dm(event, client)
    mock_orchestrator.search.assert_not_called()
    client.chat_postMessage.assert_not_called()


async def test_empty_query_replies_help(
    bot_service: SlackBotService, mock_orchestrator: AsyncMock
) -> None:
    say = AsyncMock()
    event = {"text": "<@UBOT>", "channel": "C123"}
    await bot_service._handle_mention(event, say)
    say.assert_called_once_with("질문을 입력해 주세요.", thread_ts=None)
    mock_orchestrator.search.assert_not_called()


async def test_handle_follow_up(bot_service: SlackBotService, mock_orchestrator: AsyncMock) -> None:
    import json

    client = AsyncMock()
    body = {
        "actions": [
            {
                "action_id": "follow_up_0",
                "value": json.dumps({"query": "GA4 설정 방법은?", "category": "tech"}),
            }
        ],
        "channel": {"id": "D123"},
        "message": {"ts": "111.222", "thread_ts": "111.000"},
    }
    ack = AsyncMock()
    await bot_service._handle_follow_up(ack, body, client)
    ack.assert_called_once()
    mock_orchestrator.multi_step_search.assert_called_once()
    call_args = mock_orchestrator.multi_step_search.call_args
    assert call_args[0][0].query == "GA4 설정 방법은?"
    assert call_args[0][0].category == "tech"
    client.chat_postMessage.assert_called_once()
    assert client.chat_postMessage.call_args.kwargs["thread_ts"] == "111.000"


async def test_handle_follow_up_onboarding(
    bot_service: SlackBotService, mock_orchestrator: AsyncMock
) -> None:
    import json

    client = AsyncMock()
    body = {
        "actions": [
            {
                "action_id": "follow_up_0",
                "value": json.dumps(
                    {"query": "SEO 도구 사용법", "category": "seo", "is_onboarding": True}
                ),
            }
        ],
        "channel": {"id": "D123"},
        "message": {"ts": "111.222"},
    }
    ack = AsyncMock()
    await bot_service._handle_follow_up(ack, body, client)
    call_kwargs = mock_orchestrator.multi_step_search.call_args.kwargs
    assert call_kwargs["is_onboarding"] is True


async def test_cache_hit_skips_orchestrator(
    bot_service: SlackBotService,
    mock_orchestrator: AsyncMock,
) -> None:
    cached_response = SearchResponse(
        answer="캐시된 답변",
        sources=[],
        category="all",
        metadata=SearchMetadata(chunks_retrieved=2, latency_ms=100),
    )
    mock_orchestrator.multi_step_search.return_value = cached_response

    say = AsyncMock()
    event = {"text": "<@UBOT> 캐시 테스트", "channel": "C123"}
    await bot_service._handle_mention(event, say)

    mock_orchestrator.multi_step_search.assert_called_once()
    say.assert_called_once()
