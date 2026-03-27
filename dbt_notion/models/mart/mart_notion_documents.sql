{{
    config(
        materialized='table',
        partition_by={
            "field": "last_edited_at",
            "data_type": "timestamp",
            "granularity": "day"
        },
        cluster_by=["category"]
    )
}}

-- 최종 문서 마트: breadcrumb + 전체 마크다운 + 메타데이터

select
    b.page_id,
    b.page_title,
    b.breadcrumb_path,
    b.category,
    b.client_name,
    b.depth,
    b.notion_url,
    c.full_markdown,
    c.block_count,
    c.total_sections,
    coalesce(dp.status, dp.status_kr, '') as status,
    coalesce(dp.assignee, '') as assignee,
    coalesce(dp.tags, '') as tags,
    b.last_edited_at,
    char_length(c.full_markdown) as content_length
from {{ ref('int_notion_page_breadcrumbs') }} b
inner join {{ ref('int_notion_page_content') }} c
    on b.page_id = c.page_id
left join {{ ref('int_notion_db_properties') }} dp
    on b.page_id = dp.page_id
where c.full_markdown is not null
  and char_length(c.full_markdown) > 50
