"""Slack 추출기 테스트."""

from pipeline.extract.slack_extractor import _normalize_slack_text


def test_normalize_user_mention():
    """유저 멘션 <@U123>이 @이름으로 치환되어야 한다."""
    users = {"U123ABC": "홍길동", "U456DEF": "김영희"}

    text = "<@U123ABC>님이 <@U456DEF>에게 요청했습니다."
    result = _normalize_slack_text(text, users)
    assert result == "@홍길동님이 @김영희에게 요청했습니다."


def test_normalize_unknown_user_mention():
    """알 수 없는 유저 멘션은 ID를 그대로 유지한다."""
    users = {}
    text = "<@UUNKNOWN>이 작성했습니다."
    result = _normalize_slack_text(text, users)
    assert result == "@UUNKNOWN이 작성했습니다."


def test_normalize_special_mentions():
    """<!channel>, <!here>, <!everyone> 치환."""
    users = {}
    text = "<!channel> 공지사항입니다. <!here> 확인해주세요."
    result = _normalize_slack_text(text, users)
    assert "@channel" in result
    assert "@here" in result


def test_normalize_url_with_label():
    """<url|label> → [label](url) 변환."""
    users = {}
    text = "<https://example.com|예시 링크>를 참고하세요."
    result = _normalize_slack_text(text, users)
    assert result == "[예시 링크](https://example.com)를 참고하세요."


def test_normalize_plain_url():
    """<url> → url 변환."""
    users = {}
    text = "<https://example.com>를 확인하세요."
    result = _normalize_slack_text(text, users)
    assert result == "https://example.com를 확인하세요."


def test_normalize_combined():
    """멘션 + URL이 함께 있는 경우."""
    users = {"U001": "박철수"}
    text = "<@U001>이 <https://docs.google.com|문서>를 공유했습니다."
    result = _normalize_slack_text(text, users)
    assert result == "@박철수이 [문서](https://docs.google.com)를 공유했습니다."
