"""Slack Bot 서비스 — Socket Mode로 DM 및 채널 멘션을 처리한다."""

import asyncio
import logging
import re

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from app.models.categories import CATEGORY_DEFS
from app.models.request import SearchRequest
from app.services.search_orchestrator import SearchOrchestrator
from app.services.slack_formatter import fallback_text, format_answer_blocks

logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"<@[\w]+>")

_SEARCH_TIMEOUT = 30.0
_ERROR_MSG = "검색 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
_TIMEOUT_MSG = "검색 시간이 초과되었습니다. 다시 시도해 주세요."


def _strip_mentions(text: str) -> str:
    """<@U12345> 형태의 멘션을 제거하고 양쪽 공백을 정리한다."""
    return _MENTION_RE.sub("", text).strip()


class SlackBotService:
    def __init__(
        self,
        bot_token: str,
        app_token: str,
        orchestrator: SearchOrchestrator,
    ):
        self._app = AsyncApp(token=bot_token)
        self._handler = AsyncSocketModeHandler(self._app, app_token)
        self._orchestrator = orchestrator

        self._app.event("app_mention")(self._handle_mention)
        self._app.event("message")(self._handle_dm)
        self._app.event("app_home_opened")(self._handle_home_opened)
        self._app.action("open_question_modal")(self._handle_open_modal)
        self._app.view("submit_question_modal")(self._handle_modal_submit)

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

    async def _handle_dm(self, event: dict, client) -> None:
        """DM 메시지를 처리한다."""
        if event.get("channel_type") != "im":
            return
        if event.get("bot_id"):
            return

        query = _strip_mentions(event.get("text", ""))
        thread_ts = event.get("ts")
        channel = event.get("channel")

        if not query:
            await client.chat_postMessage(channel=channel, text="질문을 입력해 주세요.", thread_ts=thread_ts)
            return

        logger.info("query category=all query=%r", query)
        request = SearchRequest(category="all", query=query)

        try:
            response = await asyncio.wait_for(self._orchestrator.search(request), timeout=_SEARCH_TIMEOUT)
        except asyncio.TimeoutError:
            await client.chat_postMessage(channel=channel, text=_TIMEOUT_MSG, thread_ts=thread_ts)
            return
        except Exception:
            logger.exception("DM search failed query=%r", query)
            await client.chat_postMessage(channel=channel, text=_ERROR_MSG, thread_ts=thread_ts)
            return

        blocks = format_answer_blocks(response)
        await client.chat_postMessage(
            channel=channel,
            blocks=blocks,
            text=fallback_text(response),
            thread_ts=thread_ts,
        )

    async def _handle_home_opened(self, client, event) -> None:
        """App Home 탭이 열릴 때 홈 화면을 렌더링한다."""
        try:
            await client.views_publish(
                user_id=event["user"],
                view={
                    "type": "home",
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": "👋 환영합니다! M-Bot입니다.",
                                "emoji": True,
                            },
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": (
                                    "Metric Studio의 사내 데이터를 학습한 AI 챗봇입니다.\n"
                                    "아래 버튼을 눌러 질문을 남겨주세요!"
                                ),
                            },
                        },
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button",
                                    "text": {
                                        "type": "plain_text",
                                        "text": "질문하기",
                                        "emoji": True,
                                    },
                                    "style": "primary",
                                    "action_id": "open_question_modal",
                                }
                            ],
                        },
                    ],
                },
            )
        except Exception:
            logger.exception("홈 탭 업데이트 실패")

    async def _handle_open_modal(self, ack, body, client) -> None:
        """'질문하기' 버튼 클릭 시 카테고리 + 질문 입력 모달을 연다."""
        await ack()
        options = [
            {"text": {"type": "plain_text", "text": modal_label}, "value": slug}
            for slug, _, _, modal_label in CATEGORY_DEFS
        ]
        try:
            await client.views_open(
                trigger_id=body["trigger_id"],
                view={
                    "type": "modal",
                    "callback_id": "submit_question_modal",
                    "title": {"type": "plain_text", "text": "M-Bot에게 질문하기"},
                    "submit": {"type": "plain_text", "text": "질문 보내기"},
                    "close": {"type": "plain_text", "text": "취소"},
                    "blocks": [
                        {
                            "type": "input",
                            "block_id": "category_block",
                            "element": {
                                "type": "static_select",
                                "action_id": "category_select",
                                "placeholder": {
                                    "type": "plain_text",
                                    "text": "카테고리를 선택하세요",
                                },
                                "options": options,
                            },
                            "label": {"type": "plain_text", "text": "질문 카테고리"},
                        },
                        {
                            "type": "input",
                            "block_id": "question_block",
                            "element": {
                                "type": "plain_text_input",
                                "action_id": "user_question",
                                "multiline": True,
                                "placeholder": {
                                    "type": "plain_text",
                                    "text": "예: 마케팅팀 이번 달 예산안 찾아줘",
                                },
                            },
                            "label": {"type": "plain_text", "text": "궁금한 내용을 입력해주세요"},
                        },
                    ],
                },
            )
        except Exception:
            logger.exception("모달 열기 실패")

    async def _handle_modal_submit(self, ack, body, client) -> None:
        """모달 제출 시 실제 검색을 수행하고 결과를 DM으로 전송한다."""
        await ack()
        user_id: str = body["user"]["id"]
        values: dict = body["view"]["state"]["values"]
        category: str = values["category_block"]["category_select"]["selected_option"]["value"]
        query: str = values["question_block"]["user_question"]["value"]

        logger.info("modal query user=%s category=%s query=%r", user_id, category, query)

        ack_ts: str | None = None
        try:
            ack_msg = await client.chat_postMessage(
                channel=user_id,
                text=(f"*[{category}]* _{query}_ :hourglass_flowing_sand:\n\n"),
            )
            ack_ts = ack_msg["ts"]
        except Exception:
            logger.exception("접수 메시지 전송 실패 (user=%s)", user_id)

        request = SearchRequest(category=category, query=query)

        try:
            response = await asyncio.wait_for(self._orchestrator.search(request), timeout=_SEARCH_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("modal search timeout user=%s query=%r", user_id, query)
            await client.chat_postMessage(channel=user_id, text=_TIMEOUT_MSG, thread_ts=ack_ts)
            return
        except Exception:
            logger.exception("modal search failed user=%s query=%r", user_id, query)
            await client.chat_postMessage(channel=user_id, text=_ERROR_MSG, thread_ts=ack_ts)
            return

        logger.info("modal response user=%s sources=%d", user_id, len(response.sources))
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"<@{user_id}>"}},
            *format_answer_blocks(response),
        ]
        try:
            await client.chat_postMessage(
                channel=user_id,
                blocks=blocks,
                text=fallback_text(response),
                thread_ts=ack_ts,
            )
        except Exception:
            logger.exception("모달 결과 DM 전송 실패 (user=%s)", user_id)

    async def _process_query(self, query: str, say, thread_ts: str | None = None) -> None:
        """쿼리를 검색하고 결과를 Slack으로 전송한다."""
        if not query:
            await say("질문을 입력해 주세요.", thread_ts=thread_ts)
            return

        logger.info("query category=all query=%r", query)
        request = SearchRequest(category="all", query=query)

        try:
            response = await asyncio.wait_for(self._orchestrator.search(request), timeout=_SEARCH_TIMEOUT)
        except asyncio.TimeoutError:
            await say(_TIMEOUT_MSG, thread_ts=thread_ts)
            return
        except Exception:
            logger.exception("mention search failed query=%r", query)
            await say(_ERROR_MSG, thread_ts=thread_ts)
            return

        blocks = format_answer_blocks(response)
        await say(blocks=blocks, text=fallback_text(response), thread_ts=thread_ts)
