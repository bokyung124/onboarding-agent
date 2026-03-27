{{
    config(
        materialized='table',
        cluster_by=["channel_id"]
    )
}}

-- 원글과 답글을 스레드 단위로 묶어 하나의 텍스트 덩어리로 만든다.
-- thread_id = coalesce(thread_ts, ts) : 스레드가 아닌 단독 메시지도 하나의 "스레드"로 취급.

with thread_groups as (
    select
        coalesce(thread_ts, ts) as thread_id,
        channel_id,
        channel_name,
        min(message_at) as thread_started_at,
        max(message_at) as thread_last_reply_at,
        string_agg(
            concat('[', user_name, '] ', text),
            '\n'
            order by message_at asc
        ) as thread_text,
        count(*) as message_count
    from {{ ref('stg_slack_messages') }}
    group by coalesce(thread_ts, ts), channel_id, channel_name
)

select * from thread_groups
