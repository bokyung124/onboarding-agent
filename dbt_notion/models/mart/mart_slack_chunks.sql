{{
    config(
        materialized='table',
        cluster_by=["category", "page_id"]
    )
}}

-- 슬랙 스레드 기반 청크를 생성한다.
-- 1 thread = 1 chunk. mart_notion_chunks와 동일한 출력 스키마.

with chunks as (
    select
        concat('slack_', t.channel_id, '_', t.thread_id) as chunk_id,
        concat('slack_', t.channel_id, '_', t.thread_id) as page_id,
        concat('#', t.channel_name) as page_title,
        concat('Slack > #', t.channel_name) as breadcrumb_path,
        coalesce(cc.category, 'uncategorized') as category,
        concat(
            'https://{{ env_var("SLACK_WORKSPACE", "workspace") }}.slack.com/archives/',
            t.channel_id,
            '/p',
            replace(t.thread_id, '.', '')
        ) as notion_url,
        cast(null as string) as client_name,
        cast(null as string) as tags,
        concat(
            '채널: #', t.channel_name, '\n',
            '카테고리: ', coalesce(cc.category, 'uncategorized'), '\n',
            '대화일시: ', cast(t.thread_started_at as string), '\n',
            '\n',
            t.thread_text
        ) as chunk_text,
        0 as section_number,
        t.thread_last_reply_at as last_edited_at,
        char_length(t.thread_text) as chunk_length
    from {{ ref('int_slack_threads') }} t
    left join {{ ref('int_slack_channel_categories') }} cc
        on t.channel_id = cc.channel_id
    where char_length(t.thread_text) > 20
      and t.message_count >= 2
)

select * from chunks
