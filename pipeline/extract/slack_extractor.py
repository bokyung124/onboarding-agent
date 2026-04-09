"""Slack 워크스페이스에서 채널 메시지와 유저 정보를 추출한다."""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from slack_sdk.web.async_client import AsyncWebClient

from pipeline.extract.slack_rate_limiter import slack_rate_limited_call

logger = logging.getLogger(__name__)


def _normalize_slack_text(text: str, users: dict[str, str]) -> str:
    """Slack mrkdwn을 표준 마크다운으로 정규화하고 멘션을 치환한다.

    변환 대상:
    - <@U12345> → @실제이름
    - <url|label> → [label](url)
    - <url> → url
    - <!channel>, <!here>, <!everyone> → @channel, @here, @everyone
    """
    # 유저 멘션 치환: <@U12345ABC> → @실제이름
    text = re.sub(
        r"<@(U[A-Z0-9]+)>",
        lambda m: f"@{users.get(m.group(1), m.group(1))}",
        text,
    )

    # 특수 멘션 치환
    text = re.sub(r"<!channel>", "@channel", text)
    text = re.sub(r"<!here>", "@here", text)
    text = re.sub(r"<!everyone>", "@everyone", text)

    # URL 치환: <url|label> → [label](url)
    text = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"[\2](\1)", text)

    # 단순 URL: <url> → url
    text = re.sub(r"<(https?://[^>]+)>", r"\1", text)

    return text


class SlackExtractor:
    """Slack API를 사용하여 채널 메시지와 유저 정보를 추출한다."""

    def __init__(
        self,
        bot_token: str,
        channel_ids: list[str] | None = None,
        workspace: str = "",
    ):
        self._client = AsyncWebClient(token=bot_token)
        self._channel_ids = channel_ids
        self._workspace = workspace
        self._users: dict[str, str] = {}  # user_id → real_name

    async def close(self) -> None:
        """리소스를 정리한다."""
        if hasattr(self._client, "session") and self._client.session:
            await self._client.session.close()

    async def extract_all(
        self,
        since_ts: str | None = None,
        on_channel_done: Callable[[list[dict]], Awaitable[None]] | None = None,
    ) -> tuple[list[dict], list[dict]]:
        """채널 메시지와 유저 정보를 추출한다.

        Args:
            since_ts: Unix timestamp 문자열. 이후 메시지만 추출 (증분).
            on_channel_done: 채널별 메시지 수집 완료 시 호출되는 async 콜백.
                             제공되면 채널별로 즉시 호출하고 메모리에 누적하지 않는다.

        Returns:
            (messages, users) 튜플. on_channel_done이 제공된 경우 messages는 빈 리스트.
        """
        extracted_at = datetime.now(timezone.utc).isoformat()

        # 1. 유저 목록 수집
        user_records = await self._fetch_users(extracted_at)
        logger.info("Fetched %d users", len(user_records))

        # 2. 채널 목록 확보
        channels = await self._resolve_channels()
        logger.info("Target channels: %d", len(channels))

        # 3. 채널별 메시지 수집
        all_messages: list[dict] = []
        for channel_id, channel_name in channels:
            messages = await self._fetch_channel_messages(
                channel_id, channel_name, since_ts, extracted_at
            )
            logger.info("  #%s: %d messages extracted", channel_name, len(messages))
            if on_channel_done is not None:
                await on_channel_done(messages)
            else:
                all_messages.extend(messages)

        logger.info("Total messages extracted: %d", len(all_messages))
        return all_messages, user_records

    async def _fetch_users(self, extracted_at: str) -> list[dict]:
        """Slack 유저 목록을 페이지네이션으로 전체 수집한다."""
        records: list[dict] = []
        cursor = None

        while True:
            kwargs: dict = {"limit": 200}
            if cursor:
                kwargs["cursor"] = cursor

            response = await slack_rate_limited_call(self._client.users_list, **kwargs)

            for member in response.get("members", []):
                if member.get("deleted", False):
                    continue
                user_id = member["id"]
                profile = member.get("profile", {})
                real_name = profile.get("real_name", member.get("name", ""))
                display_name = profile.get("display_name", "")
                is_bot = member.get("is_bot", False) or member.get("id") == "USLACKBOT"

                self._users[user_id] = real_name or display_name or user_id

                records.append(
                    {
                        "user_id": user_id,
                        "real_name": real_name,
                        "display_name": display_name,
                        "is_bot": is_bot,
                        "_extracted_at": extracted_at,
                    }
                )

            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        return records

    async def _resolve_channels(self) -> list[tuple[str, str]]:
        """대상 채널 목록을 반환한다. channel_ids가 없으면 자동 탐색."""
        if self._channel_ids:
            # 지정된 채널 ID로 info 조회
            channels: list[tuple[str, str]] = []
            for cid in self._channel_ids:
                try:
                    resp = await slack_rate_limited_call(
                        self._client.conversations_info, channel=cid
                    )
                    name = resp["channel"]["name"]
                    channels.append((cid, name))
                except Exception:
                    logger.warning("Failed to resolve channel %s, skipping", cid)
            return channels

        # 자동 탐색: public_channel만
        channels = []
        cursor = None
        while True:
            kwargs: dict = {"types": "public_channel", "limit": 200}
            if cursor:
                kwargs["cursor"] = cursor

            response = await slack_rate_limited_call(self._client.conversations_list, **kwargs)

            for ch in response.get("channels", []):
                if not ch.get("is_archived", False):
                    channels.append((ch["id"], ch["name"]))

            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        return channels

    async def _fetch_channel_messages(
        self,
        channel_id: str,
        channel_name: str,
        since_ts: str | None,
        extracted_at: str,
    ) -> list[dict]:
        """채널의 메인 메시지 + 스레드 답글을 수집한다."""
        messages: list[dict] = []
        parent_ts_list: list[str] = []
        cursor = None

        # 1단계: conversations.history로 메인 메시지 수집
        while True:
            kwargs: dict = {"channel": channel_id, "limit": 200}
            if since_ts:
                kwargs["oldest"] = since_ts
            if cursor:
                kwargs["cursor"] = cursor

            response = await slack_rate_limited_call(self._client.conversations_history, **kwargs)

            for msg in response.get("messages", []):
                if msg.get("subtype") in ("channel_join", "channel_leave", "bot_message"):
                    continue

                text = _normalize_slack_text(msg.get("text", ""), self._users)
                user_id = msg.get("user", "")
                ts = msg["ts"]
                thread_ts = msg.get("thread_ts")
                reply_count = msg.get("reply_count", 0)
                is_parent = thread_ts is None or thread_ts == ts

                messages.append(
                    {
                        "channel_id": channel_id,
                        "channel_name": channel_name,
                        "ts": ts,
                        "thread_ts": thread_ts,
                        "user_id": user_id,
                        "user_name": self._users.get(user_id, user_id),
                        "text": text,
                        "reply_count": reply_count,
                        "is_parent": is_parent,
                        "_extracted_at": extracted_at,
                    }
                )

                if is_parent and reply_count > 0:
                    parent_ts_list.append(ts)

            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        # 2단계: 스레드 답글 병렬 수집 (semaphore가 동시 실행 수 제한)
        if parent_ts_list:
            reply_tasks = [
                self._fetch_thread_replies(channel_id, channel_name, ts, extracted_at)
                for ts in parent_ts_list
            ]
            results = await asyncio.gather(*reply_tasks)
            for replies in results:
                messages.extend(replies)

        return messages

    async def _fetch_thread_replies(
        self,
        channel_id: str,
        channel_name: str,
        thread_ts: str,
        extracted_at: str,
    ) -> list[dict]:
        """스레드의 답글을 수집한다 (부모 메시지 제외)."""
        replies: list[dict] = []
        cursor = None

        while True:
            kwargs: dict = {
                "channel": channel_id,
                "ts": thread_ts,
                "limit": 200,
            }
            if cursor:
                kwargs["cursor"] = cursor

            response = await slack_rate_limited_call(self._client.conversations_replies, **kwargs)

            for msg in response.get("messages", []):
                # 부모 메시지는 이미 history에서 수집됨
                if msg["ts"] == thread_ts:
                    continue
                if msg.get("subtype") in ("channel_join", "channel_leave", "bot_message"):
                    continue

                text = _normalize_slack_text(msg.get("text", ""), self._users)
                user_id = msg.get("user", "")

                replies.append(
                    {
                        "channel_id": channel_id,
                        "channel_name": channel_name,
                        "ts": msg["ts"],
                        "thread_ts": thread_ts,
                        "user_id": user_id,
                        "user_name": self._users.get(user_id, user_id),
                        "text": text,
                        "reply_count": 0,
                        "is_parent": False,
                        "_extracted_at": extracted_at,
                    }
                )

            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        return replies
