"""Slack Bot 서비스 — Socket Mode로 DM 및 채널 멘션을 처리한다."""

import logging
import re

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from app.cache import SearchCache
from app.models.request import SearchRequest
from app.services.search_orchestrator import SearchOrchestrator
from app.services.slack_formatter import fallback_text, format_answer_blocks

logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"<@[\w]+>")


def _strip_mentions(text: str) -> str:
    """<@U12345> 형태의 멘션을 제거하고 양쪽 공백을 정리한다."""
    return _MENTION_RE.sub("", text).strip()


class SlackBotService:
    def __init__(
        self,
        bot_token: str,
        app_token: str,
        orchestrator: SearchOrchestrator,
        cache: SearchCache,
    ):
        self._app = AsyncApp(token=bot_token)
        self._handler = AsyncSocketModeHandler(self._app, app_token)
        self._orchestrator = orchestrator
        self._cache = cache

        self._app.event("app_mention")(self._handle_mention)
        self._app.event("message")(self._handle_dm)

    async def start(self) -> None:
        """Socket Mode 연결을 시작한다."""
        logger.info("Slack bot starting (Socket Mode)...")
        await self._handler.start_async()

    async def stop(self) -> None:
        """Socket Mode 연결을 종료한다."""
        logger.info("Slack bot stopping...")
        await self._handler.close_async()

    async def _handle_mention(self, event: dict, say) -> None:
        """채널에서 @멘션된 메시지를 처리한다."""
        query = _strip_mentions(event.get("text", ""))
        thread_ts = event.get("thread_ts") or event.get("ts")
        await self._process_query(query, say, thread_ts=thread_ts)

    async def _handle_dm(self, event: dict, say) -> None:
        """DM 메시지를 처리한다."""
        if event.get("channel_type") != "im":
            return
        if event.get("bot_id"):
            return

        query = _strip_mentions(event.get("text", ""))
        await self._process_query(query, say)

    async def _process_query(self, query: str, say, thread_ts: str | None = None) -> None:
        """쿼리를 검색하고 결과를 Slack으로 전송한다."""
        if not query:
            await say("질문을 입력해 주세요.", thread_ts=thread_ts)
            return

        category = "all"
        request = SearchRequest(category=category, query=query)

        cached = self._cache.get(category, query)
        if cached:
            response = cached
        else:
            response = await self._orchestrator.search(request)
            self._cache.set(category, query, response)

        blocks = format_answer_blocks(response)
        await say(blocks=blocks, text=fallback_text(response), thread_ts=thread_ts)
