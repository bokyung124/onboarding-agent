with source as (
    select * from {{ source('raw_notion', 'raw_notion_databases') }}
),

deduplicated as (
    select
        *,
        row_number() over (
            partition by database_id
            order by _extracted_at desc
        ) as _rn
    from source
),

final as (
    select
        database_id,
        parent_id,
        title as database_title,
        description,
        schema_json,
        is_inline,
        _extracted_at
    from deduplicated
    where _rn = 1
)

select * from final
