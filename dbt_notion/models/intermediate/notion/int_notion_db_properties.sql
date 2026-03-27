{{
    config(
        materialized='table',
        cluster_by=["page_id"]
    )
}}

-- 데이터베이스 하위 페이지의 속성을 JSON에서 평탄화한다.

with db_pages as (
    select
        p.page_id,
        p.parent_id as database_id,
        p.properties_json
    from {{ ref('stg_notion_pages') }} p
    where p.parent_type = 'database_id'
      and p.properties_json is not null
),

flattened as (
    select
        page_id,
        database_id,
        json_value(properties_json, '$.Status.status.name') as status,
        json_value(properties_json, '$.상태.status.name') as status_kr,
        json_value(properties_json, '$.담당자.people[0].name') as assignee,
        json_value(properties_json, '$.고객사.select.name') as client_name,
        json_value(properties_json, '$.부서.select.name') as department,
        json_value(properties_json, '$.우선순위.select.name') as priority,
        (
            select string_agg(json_value(tag, '$.name'), ', ')
            from unnest(json_query_array(properties_json, '$.태그.multi_select')) as tag
        ) as tags
    from db_pages
)

select * from flattened
