{{
    config(
        materialized='table',
        cluster_by=["category", "page_id"]
    )
}}

-- heading 기반 섹션 분할로 청크를 생성한다.
-- 각 청크에 breadcrumb + 메타데이터 컨텍스트를 주입한다.
-- 블록별 인라인 댓글은 해당 섹션에 삽입, 페이지 레벨 댓글은 별도 청크.

with block_sections as (
    select
        page_id,
        block_id,
        block_order,
        rich_text_markdown,
        heading_level,
        sum(case when heading_level is not null then 1 else 0 end)
            over (partition by page_id order by block_order) as section_number
    from {{ ref('stg_notion_blocks') }}
    where rich_text_plain is not null
      and trim(rich_text_plain) != ''
),

sections as (
    select
        page_id,
        section_number,
        string_agg(
            rich_text_markdown,
            '\n'
            order by block_order
        ) as section_text
    from block_sections
    group by page_id, section_number
),

-- 블록별 인라인 댓글을 섹션에 매핑
section_comments as (
    select
        bs.page_id,
        bs.section_number,
        string_agg(
            c.content_markdown,
            '\n'
            order by c.created_at
        ) as comments_text
    from {{ ref('stg_notion_comments') }} c
    inner join block_sections bs on c.parent_block_id = bs.block_id
    group by bs.page_id, bs.section_number
),

-- 페이지 레벨 댓글 (parent_block_id가 없는 댓글)
page_comments as (
    select
        page_id,
        count(*) as comment_count,
        string_agg(
            content_markdown,
            '\n\n'
            order by created_at
        ) as comments_text
    from {{ ref('stg_notion_comments') }}
    where parent_block_id is null
    group by page_id
),

sections_with_overlap as (
    select
        page_id,
        section_number,
        case
            when lag(section_text) over (partition by page_id order by section_number) is not null
            then concat(
                right(
                    lag(section_text) over (partition by page_id order by section_number),
                    500
                ),
                '\n',
                section_text
            )
            else section_text
        end as section_text,
        char_length(section_text) as original_length
    from sections
),

chunks as (
    select
        d.page_id,
        d.page_title,
        d.breadcrumb_path,
        d.category,
        d.is_onboarding,
        d.client_name,
        d.notion_url,
        d.tags,
        d.last_edited_at,
        s.section_number,
        concat(d.page_id, '_', cast(s.section_number as string)) as chunk_id,
        concat(
            s.section_text,
            case when sc.comments_text is not null
                 then concat('\n\n[댓글/피드백]\n', sc.comments_text)
                 else '' end
        ) as chunk_text,
        s.original_length as chunk_length
    from {{ ref('mart_notion_documents') }} d
    inner join sections_with_overlap s on d.page_id = s.page_id
    left join section_comments sc
        on s.page_id = sc.page_id and s.section_number = sc.section_number
    where s.original_length > 20
      and s.original_length <= 8000
),

comment_chunks as (
    select
        d.page_id,
        d.page_title,
        d.breadcrumb_path,
        d.category,
        d.is_onboarding,
        d.client_name,
        d.notion_url,
        d.tags,
        d.last_edited_at,
        999 as section_number,
        concat(d.page_id, '_comments') as chunk_id,
        concat(
            '[페이지 댓글]\n',
            pc.comments_text
        ) as chunk_text,
        char_length(pc.comments_text) as chunk_length
    from {{ ref('mart_notion_documents') }} d
    inner join page_comments pc on d.page_id = pc.page_id
    where pc.comment_count > 0
)

select * from chunks
union all
select * from comment_chunks
