{{
    config(
        materialized='view'
    )
}}

-- Slack 메시지를 dedup하고 타임스탬프를 변환한다.

with source as (
    select * from {{ source('raw_slack', 'raw_slack_messages') }}
),

deduplicated as (
    select
        *,
        row_number() over (
            partition by channel_id, cast(ts as string)
            order by _extracted_at desc
        ) as _rn
    from source
),

final as (
    select
        channel_id,
        channel_name,
        ts,
        thread_ts,
        user_id,
        user_name,
        text,
        reply_count,
        is_parent,
        -- Unix timestamp (FLOAT64) → TIMESTAMP 변환
        timestamp_seconds(cast(floor(ts) as int64)) as message_at,
        _extracted_at
    from deduplicated
    where _rn = 1
)

select * from final
