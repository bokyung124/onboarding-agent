{{
    config(
        materialized='table',
        cluster_by=["page_id"]
    )
}}

-- 블록을 페이지별로 순서대로 조립하여 마크다운 문서를 생성한다.
-- heading 기반 섹션 번호도 부여하여 청킹에 활용한다.

with ordered_blocks as (
    select
        page_id,
        block_id,
        block_type,
        block_order,
        rich_text_plain,
        rich_text_markdown,
        heading_level,
        -- heading이 나올 때마다 섹션 번호 증가
        sum(case when heading_level is not null then 1 else 0 end)
            over (partition by page_id order by block_order) as section_number
    from {{ ref('stg_notion_blocks') }}
    where rich_text_plain is not null
      and trim(rich_text_plain) != ''
),

page_full_text as (
    select
        page_id,
        string_agg(
            rich_text_markdown,
            '\n'
            order by block_order
        ) as full_markdown,
        count(*) as block_count,
        max(section_number) as total_sections
    from ordered_blocks
    group by page_id
)

select * from page_full_text
