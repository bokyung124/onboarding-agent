"""SearchResponse를 Slack Block Kit 형식으로 변환한다."""

import re

from app.models.response import SearchResponse


def _to_mrkdwn(text: str) -> str:
    """마크다운을 Slack mrkdwn으로 변환한다."""
    # **bold** → *bold*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    # ### heading → *heading*
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)
    return text


def format_answer_blocks(response: SearchResponse) -> list[dict]:
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
