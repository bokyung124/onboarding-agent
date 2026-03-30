{{
    config(
        materialized='table'
    )
}}

-- 모든 Slack 채널을 'all' 카테고리로 분류한다.

select distinct
    channel_id,
    channel_name,
    'all' as category
from {{ ref('stg_slack_messages') }}
