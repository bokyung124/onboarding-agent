{{
    config(
        materialized='view'
    )
}}

-- Slack 유저를 dedup하고 봇을 제외한다.

with source as (
    select * from {{ source('raw_slack', 'raw_slack_users') }}
),

deduplicated as (
    select
        *,
        row_number() over (
            partition by user_id
            order by _extracted_at desc
        ) as _rn
    from source
),

final as (
    select
        user_id,
        real_name,
        display_name,
        is_bot,
        _extracted_at
    from deduplicated
    where _rn = 1
      and is_bot = false
)

select * from final
