with source as (
    select * from {{ source('raw_notion', 'raw_notion_blocks') }}
),

deduplicated as (
    select
        *,
        row_number() over (
            partition by block_id
            order by _extracted_at desc
        ) as _rn
    from source
),

final as (
    select
        block_id,
        page_id,
        parent_block_id,
        block_type,
        block_order,
        has_children,
        rich_text_plain,
        rich_text_markdown,
        case
            when block_type = 'heading_1' then 1
            when block_type = 'heading_2' then 2
            when block_type = 'heading_3' then 3
        end as heading_level,
        timestamp(last_edited_time) as last_edited_at
    from deduplicated
    where _rn = 1
      and block_type not in ('child_page', 'child_database', 'unsupported', 'table_of_contents')
)

select * from final
