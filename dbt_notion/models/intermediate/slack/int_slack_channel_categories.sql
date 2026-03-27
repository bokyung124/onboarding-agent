{{
    config(
        materialized='table'
    )
}}

-- Slack 채널을 검색 카테고리에 매핑한다.
-- seeds/slack_channel_categories.csv를 기반으로 매핑하며,
-- 매핑되지 않는 채널은 'uncategorized'로 분류한다.

with channels as (
    select distinct channel_id, channel_name
    from {{ ref('stg_slack_messages') }}
),

seed_mapping as (
    select * from {{ ref('slack_channel_categories') }}
),

mapped as (
    select
        c.channel_id,
        c.channel_name,
        coalesce(sm.category, 'uncategorized') as category
    from channels c
    left join seed_mapping sm
        on lower(c.channel_name) = lower(sm.channel_name)
)

select * from mapped
