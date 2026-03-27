with source as (
    select * from {{ source('raw_notion', 'raw_notion_pages') }}
    where is_archived = false
),

deduplicated as (
    select
        *,
        row_number() over (
            partition by page_id
            order by _extracted_at desc
        ) as _rn
    from source
),

final as (
    select
        page_id,
        parent_type,
        parent_id,
        title as page_title,
        url as notion_url,
        timestamp(created_time) as created_at,
        timestamp(last_edited_time) as last_edited_at,
        properties_json,
        _extracted_at
    from deduplicated
    where _rn = 1
)

select * from final
