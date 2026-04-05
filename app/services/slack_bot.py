"""Slack Bot 서비스 — Socket Mode로 DM 및 채널 멘션을 처리한다."""

import asyncio
import json
import logging
import re

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from app.cache import ConversationCache
from app.models.categories import CATEGORY_DEFS, ONBOARDING_CATEGORY_DEFS
from app.models.request import OnboardingSearchRequest, SearchRequest
from app.services.search_orchestrator import SearchOrchestrator
from app.services.slack_formatter import (
    fallback_checklist_text,
    fallback_text,
    format_answer_blocks,
    format_checklist_blocks,
)

logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"<@[\w]+>")

_DEFAULT_SEARCH_TIMEOUT = 120.0
_PROGRESS_DELAY = 10.0
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
        search_timeout: float = _DEFAULT_SEARCH_TIMEOUT,
        conversation_cache: ConversationCache | None = None,
    ):
        self._app = AsyncApp(token=bot_token)
        self._handler = AsyncSocketModeHandler(self._app, app_token)
        self._orchestrator = orchestrator
        self._search_timeout = search_timeout
        self._conversation_cache = conversation_cache

        self._app.event("app_mention")(self._handle_mention)
        self._app.event("message")(self._handle_dm)
        self._app.event("app_home_opened")(self._handle_home_opened)
        self._app.action("open_question_modal")(self._handle_open_modal)
        self._app.action("open_onboarding_modal")(self._handle_open_onboarding_modal)
        self._app.action("open_checklist_modal")(self._handle_open_checklist_modal)
        self._app.action("open_drip_modal")(self._handle_open_drip_modal)
        self._app.action(re.compile(r"^follow_up_\d+$"))(self._handle_follow_up)
        self._app.action(re.compile(r"^checklist_step_\d+$"))(self._handle_follow_up)
        self._app.view("submit_question_modal")(self._handle_modal_submit)
        self._app.view("submit_onboarding_modal")(self._handle_onboarding_modal_submit)
        self._app.view("submit_checklist_modal")(self._handle_checklist_modal_submit)
        self._app.view("submit_drip_modal")(self._handle_drip_modal_submit)

    async def start(self) -> None:
        """Socket Mode 연결을 시작한다."""
        logger.info("Slack bot starting (Socket Mode)...")
        await self._handler.start_async()

    async def stop(self) -> None:
        """Socket Mode 연결을 종료한다."""
        logger.info("Slack bot stopping...")
        await self._handler.close_async()

    async def _run_search_with_progress(self, client, channel: str, ack_ts: str | None, coro):
        """검색 코루틴을 실행하면서 일정 시간 후 진행 상태를 업데이트한다."""
        task = asyncio.create_task(coro)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=_PROGRESS_DELAY)
        except asyncio.TimeoutError:
            if ack_ts:
                try:
                    await client.chat_update(
                        channel=channel,
                        ts=ack_ts,
                        text="답변을 생성하고 있어요... :writing_hand:",
                    )
                except Exception:
                    pass
            return await asyncio.wait_for(task, timeout=self._search_timeout - _PROGRESS_DELAY)

    async def _handle_mention(self, event: dict, say) -> None:
        """채널에서 @멘션된 메시지를 처리한다."""
        query = _strip_mentions(event.get("text", ""))
        thread_ts = event.get("thread_ts") or event.get("ts")
        channel = event.get("channel", "")
        user_id = event.get("user", "")
        await self._process_query(query, say, thread_ts=thread_ts, channel=channel, user_id=user_id)

    async def _handle_dm(self, event: dict, client) -> None:
        """DM 메시지를 처리한다."""
        if event.get("channel_type") != "im":
            return
        if event.get("bot_id"):
            return

        query = _strip_mentions(event.get("text", ""))
        thread_ts = event.get("thread_ts") or event.get("ts")
        channel = event.get("channel", "")

        if not query:
            await client.chat_postMessage(
                channel=channel, text="질문을 입력해 주세요.", thread_ts=thread_ts
            )
            return

        logger.info("query category=all query=%r", query)

        history = (
            self._conversation_cache.get(channel, thread_ts)
            if self._conversation_cache and thread_ts
            else []
        )
        request = SearchRequest(category="all", query=query)

        try:
            user_id = event.get("user", "")
            response = await asyncio.wait_for(
                self._orchestrator.multi_step_search(
                    request, conversation_history=history or None, user_id=user_id
                ),
                timeout=self._search_timeout,
            )
        except asyncio.TimeoutError:
            await client.chat_postMessage(channel=channel, text=_TIMEOUT_MSG, thread_ts=thread_ts)
            return
        except Exception:
            logger.exception("DM search failed query=%r", query)
            await client.chat_postMessage(channel=channel, text=_ERROR_MSG, thread_ts=thread_ts)
            return

        if self._conversation_cache and thread_ts:
            self._conversation_cache.append(channel, thread_ts, query, response.answer)

        blocks = format_answer_blocks(response)
        await client.chat_postMessage(
            channel=channel,
            blocks=blocks,
            text=fallback_text(response),
            thread_ts=thread_ts,
        )

    async def _handle_follow_up(self, ack, body, client) -> None:
        """후속 질문 버튼 클릭 시 해당 질문으로 재검색한다."""
        await ack()
        action = body["actions"][0]
        try:
            payload = json.loads(action["value"])
            query = payload["query"]
            category = payload.get("category", "all")
            is_onboarding = payload.get("is_onboarding", False)
        except (json.JSONDecodeError, KeyError):
            query = action.get("value", "")
            category = "all"
            is_onboarding = False

        channel = body["channel"]["id"]
        thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]

        if not query:
            return

        logger.info("follow_up query category=%s query=%r", category, query)

        history = (
            self._conversation_cache.get(channel, thread_ts)
            if self._conversation_cache and thread_ts
            else []
        )

        if is_onboarding:
            request = OnboardingSearchRequest(category=category, query=query)
        else:
            request = SearchRequest(category=category, query=query)

        user_id = body.get("user", {}).get("id", "")
        try:
            response = await asyncio.wait_for(
                self._orchestrator.multi_step_search(
                    request,
                    is_onboarding=is_onboarding,
                    conversation_history=history or None,
                    user_id=user_id or None,
                ),
                timeout=self._search_timeout,
            )
        except asyncio.TimeoutError:
            await client.chat_postMessage(channel=channel, text=_TIMEOUT_MSG, thread_ts=thread_ts)
            return
        except Exception:
            logger.exception("follow_up search failed query=%r", query)
            await client.chat_postMessage(channel=channel, text=_ERROR_MSG, thread_ts=thread_ts)
            return

        if self._conversation_cache and thread_ts:
            self._conversation_cache.append(channel, thread_ts, query, response.answer)

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
                                },
                                {
                                    "type": "button",
                                    "text": {
                                        "type": "plain_text",
                                        "text": "온보딩 질문하기",
                                        "emoji": True,
                                    },
                                    "action_id": "open_onboarding_modal",
                                },
                                {
                                    "type": "button",
                                    "text": {
                                        "type": "plain_text",
                                        "text": "온보딩 체크리스트",
                                        "emoji": True,
                                    },
                                    "action_id": "open_checklist_modal",
                                },
                                {
                                    "type": "button",
                                    "text": {
                                        "type": "plain_text",
                                        "text": "온보딩 드립 등록",
                                        "emoji": True,
                                    },
                                    "action_id": "open_drip_modal",
                                },
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

    async def _handle_open_onboarding_modal(self, ack, body, client) -> None:
        """'온보딩 질문하기' 버튼 클릭 시 온보딩 카테고리 + 질문 입력 모달을 연다."""
        await ack()
        options = [
            {"text": {"type": "plain_text", "text": modal_label}, "value": slug}
            for slug, _, _, modal_label in ONBOARDING_CATEGORY_DEFS
        ]
        try:
            await client.views_open(
                trigger_id=body["trigger_id"],
                view={
                    "type": "modal",
                    "callback_id": "submit_onboarding_modal",
                    "title": {"type": "plain_text", "text": "온보딩 질문하기"},
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
                                    "text": "분야를 선택하세요",
                                },
                                "options": options,
                            },
                            "label": {
                                "type": "plain_text",
                                "text": "온보딩 분야",
                            },
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
                                    "text": "예: SEO 온보딩 절차 알려줘",
                                },
                            },
                            "label": {
                                "type": "plain_text",
                                "text": "궁금한 내용을 입력해주세요",
                            },
                        },
                    ],
                },
            )
        except Exception:
            logger.exception("온보딩 모달 열기 실패")

    async def _handle_open_checklist_modal(self, ack, body, client) -> None:
        """'온보딩 체크리스트' 버튼 클릭 시 카테고리 선택 모달을 연다."""
        await ack()
        options = [
            {"text": {"type": "plain_text", "text": modal_label}, "value": slug}
            for slug, _, _, modal_label in ONBOARDING_CATEGORY_DEFS
            if slug != "all"
        ]
        try:
            await client.views_open(
                trigger_id=body["trigger_id"],
                view={
                    "type": "modal",
                    "callback_id": "submit_checklist_modal",
                    "title": {"type": "plain_text", "text": "온보딩 체크리스트"},
                    "submit": {"type": "plain_text", "text": "체크리스트 보기"},
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
                                    "text": "온보딩 분야를 선택하세요",
                                },
                                "options": options,
                            },
                            "label": {
                                "type": "plain_text",
                                "text": "온보딩 분야",
                            },
                        },
                    ],
                },
            )
        except Exception:
            logger.exception("체크리스트 모달 열기 실패")

    async def _handle_checklist_modal_submit(self, ack, body, client) -> None:
        """체크리스트 모달 제출 시 학습 경로를 생성하여 DM으로 전송한다."""
        await ack()
        user_id: str = body["user"]["id"]
        values: dict = body["view"]["state"]["values"]
        category: str = values["category_block"]["category_select"]["selected_option"]["value"]

        logger.info("checklist modal user=%s category=%s", user_id, category)

        ack_ts: str | None = None
        try:
            ack_msg = await client.chat_postMessage(
                channel=user_id,
                text=(
                    f"*[온보딩 체크리스트/{category.upper()}]* :hourglass_flowing_sand: 생성 중..."
                ),
            )
            ack_ts = ack_msg["ts"]
        except Exception:
            logger.exception("체크리스트 접수 메시지 전송 실패 (user=%s)", user_id)

        try:
            response = await self._run_search_with_progress(
                client,
                user_id,
                ack_ts,
                self._orchestrator.generate_checklist(category),
            )
        except asyncio.TimeoutError:
            logger.warning("checklist timeout user=%s category=%s", user_id, category)
            await client.chat_postMessage(channel=user_id, text=_TIMEOUT_MSG, thread_ts=ack_ts)
            return
        except Exception:
            logger.exception("checklist failed user=%s category=%s", user_id, category)
            await client.chat_postMessage(channel=user_id, text=_ERROR_MSG, thread_ts=ack_ts)
            return

        logger.info("checklist response user=%s steps=%d", user_id, len(response.steps))
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"<@{user_id}>"}},
            *format_checklist_blocks(response),
        ]
        try:
            await client.chat_postMessage(
                channel=user_id,
                blocks=blocks,
                text=fallback_checklist_text(response),
                thread_ts=ack_ts,
            )
        except Exception:
            logger.exception("체크리스트 결과 DM 전송 실패 (user=%s)", user_id)

    async def _handle_onboarding_modal_submit(self, ack, body, client) -> None:
        """온보딩 모달 제출 시 온보딩 검색을 수행하고 결과를 DM으로 전송한다."""
        await ack()
        user_id: str = body["user"]["id"]
        values: dict = body["view"]["state"]["values"]
        category: str = values["category_block"]["category_select"]["selected_option"]["value"]
        query: str = values["question_block"]["user_question"]["value"]

        logger.info("onboarding modal query user=%s category=%s query=%r", user_id, category, query)

        ack_ts: str | None = None
        try:
            ack_msg = await client.chat_postMessage(
                channel=user_id,
                text=f"*[온보딩/{category.upper()}]* _{query}_ :hourglass_flowing_sand:\n\n",
            )
            ack_ts = ack_msg["ts"]
        except Exception:
            logger.exception("접수 메시지 전송 실패 (user=%s)", user_id)

        request = OnboardingSearchRequest(category=category, query=query)

        try:
            response = await self._run_search_with_progress(
                client,
                user_id,
                ack_ts,
                self._orchestrator.search(request, is_onboarding=True, user_id=user_id),
            )
        except asyncio.TimeoutError:
            logger.warning("onboarding search timeout user=%s query=%r", user_id, query)
            await client.chat_postMessage(channel=user_id, text=_TIMEOUT_MSG, thread_ts=ack_ts)
            return
        except Exception:
            logger.exception("onboarding search failed user=%s query=%r", user_id, query)
            await client.chat_postMessage(channel=user_id, text=_ERROR_MSG, thread_ts=ack_ts)
            return

        logger.info("onboarding response user=%s sources=%d", user_id, len(response.sources))
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"<@{user_id}>"}},
            *format_answer_blocks(response, is_onboarding=True),
        ]
        try:
            await client.chat_postMessage(
                channel=user_id,
                blocks=blocks,
                text=fallback_text(response),
                thread_ts=ack_ts,
            )
        except Exception:
            logger.exception("온보딩 결과 DM 전송 실패 (user=%s)", user_id)

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
            response = await self._run_search_with_progress(
                client,
                user_id,
                ack_ts,
                self._orchestrator.search(request, user_id=user_id),
            )
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

    async def _process_query(
        self,
        query: str,
        say,
        thread_ts: str | None = None,
        channel: str = "",
        user_id: str = "",
    ) -> None:
        """쿼리를 검색하고 결과를 Slack으로 전송한다."""
        if not query:
            await say("질문을 입력해 주세요.", thread_ts=thread_ts)
            return

        logger.info("query category=all query=%r", query)

        history = (
            self._conversation_cache.get(channel, thread_ts)
            if self._conversation_cache and channel and thread_ts
            else []
        )
        request = SearchRequest(category="all", query=query)

        try:
            response = await asyncio.wait_for(
                self._orchestrator.multi_step_search(
                    request, conversation_history=history or None, user_id=user_id or None
                ),
                timeout=self._search_timeout,
            )
        except asyncio.TimeoutError:
            await say(_TIMEOUT_MSG, thread_ts=thread_ts)
            return
        except Exception:
            logger.exception("mention search failed query=%r", query)
            await say(_ERROR_MSG, thread_ts=thread_ts)
            return

        if self._conversation_cache and channel and thread_ts:
            self._conversation_cache.append(channel, thread_ts, query, response.answer)

        blocks = format_answer_blocks(response)
        await say(blocks=blocks, text=fallback_text(response), thread_ts=thread_ts)

    async def _handle_open_drip_modal(self, ack, body, client) -> None:
        """'온보딩 드립 등록' 버튼 클릭 시 카테고리 + 입사일 모달을 연다."""
        await ack()
        options = [
            {"text": {"type": "plain_text", "text": modal_label}, "value": slug}
            for slug, _, _, modal_label in ONBOARDING_CATEGORY_DEFS
            if slug != "all"
        ]
        try:
            await client.views_open(
                trigger_id=body["trigger_id"],
                view={
                    "type": "modal",
                    "callback_id": "submit_drip_modal",
                    "title": {"type": "plain_text", "text": "온보딩 드립 등록"},
                    "submit": {"type": "plain_text", "text": "등록하기"},
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
                                    "text": "온보딩 분야를 선택하세요",
                                },
                                "options": options,
                            },
                            "label": {
                                "type": "plain_text",
                                "text": "온보딩 분야",
                            },
                        },
                        {
                            "type": "input",
                            "block_id": "hire_date_block",
                            "element": {
                                "type": "datepicker",
                                "action_id": "hire_date_select",
                                "placeholder": {
                                    "type": "plain_text",
                                    "text": "입사일을 선택하세요",
                                },
                            },
                            "label": {
                                "type": "plain_text",
                                "text": "입사일",
                            },
                        },
                    ],
                },
            )
        except Exception:
            logger.exception("드립 모달 열기 실패")

    async def _handle_drip_modal_submit(self, ack, body, client) -> None:
        """드립 모달 제출 시 유저를 드립 캠페인에 등록한다."""
        await ack()
        user_id: str = body["user"]["id"]
        values: dict = body["view"]["state"]["values"]
        category: str = values["category_block"]["category_select"]["selected_option"]["value"]
        hire_date_str: str = values["hire_date_block"]["hire_date_select"]["selected_date"]

        logger.info(
            "drip register user=%s category=%s hire_date=%s",
            user_id,
            category,
            hire_date_str,
        )

        try:
            from datetime import date

            from google.cloud import bigquery

            from pipeline.drip.drip_sender import ensure_drip_table, register_user

            settings = self._orchestrator._vector_search._settings
            bq_client = bigquery.Client(project=settings.gcp_project_id)
            ensure_drip_table(bq_client, settings.gcp_project_id, settings.bq_dataset)
            register_user(
                bq_client,
                settings.gcp_project_id,
                settings.bq_dataset,
                user_id=user_id,
                slack_user_id=user_id,
                category=category,
                hire_date=date.fromisoformat(hire_date_str),
            )
            bq_client.close()
            await client.chat_postMessage(
                channel=user_id,
                text=(
                    f":white_check_mark: 온보딩 드립 캠페인에 등록되었습니다!\n"
                    f"분야: *{category}*, 입사일: {hire_date_str}\n"
                    f"Day 1, 3, 7에 학습 안내 메시지를 받게 됩니다."
                ),
            )
        except Exception:
            logger.exception("drip registration failed user=%s", user_id)
            await client.chat_postMessage(
                channel=user_id,
                text="드립 캠페인 등록 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
            )
