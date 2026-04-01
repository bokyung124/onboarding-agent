"""온보딩 드립 캠페인: 대상 유저 조회, 콘텐츠 전송, 전송 완료 마킹."""

import logging
from datetime import date, datetime, timezone

from google.cloud import bigquery
from slack_sdk import WebClient

logger = logging.getLogger(__name__)

_DRIP_TABLE_SCHEMA = [
    bigquery.SchemaField("user_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("slack_user_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("category", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("hire_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("day1_sent", "BOOLEAN", mode="REQUIRED"),
    bigquery.SchemaField("day3_sent", "BOOLEAN", mode="REQUIRED"),
    bigquery.SchemaField("day7_sent", "BOOLEAN", mode="REQUIRED"),
    bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
]

DRIP_DAYS = [1, 3, 7]


def ensure_drip_table(bq_client: bigquery.Client, project_id: str, dataset: str) -> None:
    """raw_drip_users 테이블이 없으면 생성한다."""
    table_id = f"{project_id}.{dataset}.raw_drip_users"
    table = bigquery.Table(table_id, schema=_DRIP_TABLE_SCHEMA)
    bq_client.create_table(table, exists_ok=True)
    logger.info("drip table ensured: %s", table_id)


def register_user(
    bq_client: bigquery.Client,
    project_id: str,
    dataset: str,
    user_id: str,
    slack_user_id: str,
    category: str,
    hire_date: date,
) -> None:
    """드립 캠페인에 유저를 등록한다."""
    table_id = f"{project_id}.{dataset}.raw_drip_users"
    row = {
        "user_id": user_id,
        "slack_user_id": slack_user_id,
        "category": category,
        "hire_date": hire_date.isoformat(),
        "day1_sent": False,
        "day3_sent": False,
        "day7_sent": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    errors = bq_client.insert_rows_json(table_id, [row])
    if errors:
        raise RuntimeError(f"Failed to register drip user: {errors}")
    logger.info("drip user registered: %s category=%s hire_date=%s", user_id, category, hire_date)


def find_due_users(
    bq_client: bigquery.Client, project_id: str, dataset: str, today: date | None = None
) -> list[dict]:
    """오늘 전송 대상인 유저 목록을 반환한다.

    각 유저에 대해 해당하는 day (1, 3, 7)를 포함한다.
    """
    today = today or date.today()
    table_id = f"{project_id}.{dataset}.raw_drip_users"
    results: list[dict] = []

    for day_n in DRIP_DAYS:
        target_hire = today.isoformat()  # DayN: hire_date = today - (day_n - 1)
        col = f"day{day_n}_sent"
        query = f"""
        SELECT user_id, slack_user_id, category, hire_date
        FROM `{table_id}`
        WHERE {col} = FALSE
          AND DATE_DIFF(DATE('{target_hire}'), hire_date, DAY) = {day_n - 1}
        """
        job = bq_client.query(query)
        for row in job.result():
            results.append(
                {
                    "user_id": row.user_id,
                    "slack_user_id": row.slack_user_id,
                    "category": row.category,
                    "hire_date": row.hire_date,
                    "drip_day": day_n,
                }
            )
    logger.info("drip due users found: %d", len(results))
    return results


def build_drip_message(category: str, drip_day: int) -> str:
    """드립 Day별 메시지를 생성한다."""
    from app.models.categories import ONBOARDING_CATEGORY_NAMES

    cat_name = ONBOARDING_CATEGORY_NAMES.get(category, category)

    if drip_day == 1:
        return (
            f":wave: 환영합니다! *{cat_name}* 팀 온보딩을 시작합니다.\n\n"
            f"온보딩 체크리스트를 확인해보세요. "
            f"M-Bot 홈 탭에서 '온보딩 체크리스트' 버튼을 눌러 "
            f"*{cat_name}* 분야를 선택하면 단계별 학습 경로를 받을 수 있습니다.\n\n"
            f"궁금한 점은 언제든 DM으로 질문해주세요!"
        )
    elif drip_day == 3:
        return (
            f":books: *{cat_name}* 온보딩 3일차입니다!\n\n"
            f"기본 세팅과 도구 사용법은 익숙해지셨나요? "
            f"아직 궁금한 점이 있다면 DM으로 질문해주세요.\n\n"
            f"_추천 질문:_ `{cat_name} 주요 업무 프로세스는?`"
        )
    else:  # day 7
        return (
            f":star: *{cat_name}* 온보딩 7일차, 첫 주를 마무리합니다!\n\n"
            f"이제 실무에 본격적으로 참여할 준비가 되었을 거예요. "
            f"심화 내용이 궁금하다면 언제든 질문해주세요.\n\n"
            f"_추천 질문:_ `{cat_name} 팀 협업 방식은?`"
        )


def send_drip_message(slack_client: WebClient, slack_user_id: str, message: str) -> None:
    """Slack DM으로 드립 메시지를 전송한다."""
    slack_client.chat_postMessage(channel=slack_user_id, text=message)
    logger.info("drip message sent to %s", slack_user_id)


def mark_sent(
    bq_client: bigquery.Client,
    project_id: str,
    dataset: str,
    user_id: str,
    drip_day: int,
) -> None:
    """전송 완료를 마킹한다."""
    table_id = f"{project_id}.{dataset}.raw_drip_users"
    col = f"day{drip_day}_sent"
    query = f"""
    UPDATE `{table_id}`
    SET {col} = TRUE
    WHERE user_id = '{user_id}'
    """
    bq_client.query(query).result()
    logger.info("drip mark_sent user=%s day=%d", user_id, drip_day)
