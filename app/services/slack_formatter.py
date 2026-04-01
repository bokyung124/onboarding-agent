"""SearchResponse / ChecklistResponse를 Slack Block Kit 형식으로 변환한다."""

import json
import re

from app.models.response import ChecklistResponse, SearchResponse


def _to_mrkdwn(text: str) -> str:
    """마크다운을 Slack mrkdwn으로 변환한다."""
    # **bold** → *bold*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    # ### heading → *heading*
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)
    # [text](url) → <url|text>
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", r"<\2|\1>", text)
    return text


def format_answer_blocks(response: SearchResponse, *, is_onboarding: bool = False) -> list[dict]:
    """SearchResponse를 Slack Block Kit 블록 리스트로 변환한다."""
    blocks: list[dict] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": _to_mrkdwn(response.answer)},
        },
    ]

    if response.sources:
        source_lines = []
        for i, src in enumerate(response.sources, 1):
            label = f"[{src.source_type.upper()}]" if src.source_type else ""
            source_lines.append(f"{i}. <{src.url}|{src.title}> {label}")

        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "*출처*\n" + "\n".join(source_lines),
                    }
                ],
            }
        )

    if response.follow_up_questions:
        blocks.append({"type": "divider"})
        buttons = []
        for i, question in enumerate(response.follow_up_questions):
            payload_dict: dict = {"query": question, "category": response.category}
            if is_onboarding:
                payload_dict["is_onboarding"] = True
            payload = json.dumps(payload_dict, ensure_ascii=False)
            buttons.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": question[:75], "emoji": True},
                    "action_id": f"follow_up_{i}",
                    "value": payload,
                }
            )
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "*이런 것도 궁금하지 않으세요?*"}],
            }
        )
        blocks.append({"type": "actions", "elements": buttons})

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"검색 참고 청크 {response.metadata.chunks_retrieved}개"
                        f" | 응답 시간 {response.metadata.latency_ms}ms"
                    ),
                }
            ],
        }
    )

    return blocks


def fallback_text(response: SearchResponse) -> str:
    """Block Kit 미지원 클라이언트용 폴백 텍스트."""
    return response.answer[:3000]


def format_checklist_blocks(response: ChecklistResponse) -> list[dict]:
    """ChecklistResponse를 Slack Block Kit 블록 리스트로 변환한다."""
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": response.title[:150], "emoji": True},
        },
    ]

    for step in response.steps:
        payload = json.dumps(
            {
                "query": step.search_query,
                "category": response.category,
                "is_onboarding": True,
            },
            ensure_ascii=False,
        )
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{step.step_number}. {step.title}*\n{step.description}",
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "자세히 보기", "emoji": True},
                    "action_id": f"checklist_step_{step.step_number}",
                    "value": payload,
                },
            }
        )

    if response.sources:
        source_lines = []
        for i, src in enumerate(response.sources, 1):
            label = f"[{src.source_type.upper()}]" if src.source_type else ""
            source_lines.append(f"{i}. <{src.url}|{src.title}> {label}")
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "*참고 문서*\n" + "\n".join(source_lines)}],
            }
        )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"검색 참고 청크 {response.metadata.chunks_retrieved}개"
                        f" | 응답 시간 {response.metadata.latency_ms}ms"
                    ),
                }
            ],
        }
    )

    return blocks


def fallback_checklist_text(response: ChecklistResponse) -> str:
    """Block Kit 미지원 클라이언트용 체크리스트 폴백 텍스트."""
    lines = [response.title]
    for step in response.steps:
        lines.append(f"{step.step_number}. {step.title}: {step.description}")
    return "\n".join(lines)[:3000]
