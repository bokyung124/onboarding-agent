with source as (
    select * from {{ source('raw_notion', 'raw_notion_comments') }}
),

deduplicated as (
    select
        *,
        row_number() over (
            partition by comment_id
            order by _extracted_at desc
        ) as _rn
    from source
),

final as (
    select
        comment_id,
        page_id,
        parent_block_id,
        discussion_id,
        created_by_id,
        content_plain,
        content_markdown,
        timestamp(created_time) as created_at,
        timestamp(last_edited_time) as last_edited_at
    from deduplicated
    where _rn = 1
      and trim(content_plain) != ''
)

select * from final
