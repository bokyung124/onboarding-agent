"""드립 캠페인 테스트."""

from pipeline.drip.drip_sender import build_drip_message


def test_build_drip_message_day1() -> None:
    msg = build_drip_message("seo", 1)
    assert "환영합니다" in msg
    assert "체크리스트" in msg


def test_build_drip_message_day3() -> None:
    msg = build_drip_message("seo", 3)
    assert "3일차" in msg


def test_build_drip_message_day7() -> None:
    msg = build_drip_message("seo", 7)
    assert "7일차" in msg
    assert "심화" in msg


def test_drip_days_content_varies() -> None:
    """각 Day별 메시지가 서로 다르다."""
    messages = {build_drip_message("tech", d) for d in [1, 3, 7]}
    assert len(messages) == 3
