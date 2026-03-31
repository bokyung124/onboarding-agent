{{
    config(
        materialized='table',
        partition_by={
            "field": "last_edited_at",
            "data_type": "timestamp",
            "granularity": "day"
        },
        cluster_by=["category", "page_id"]
    )
}}

-- 재귀 CTE로 페이지 계층 경로(breadcrumb)와 카테고리 분류를 생성한다.
-- depth=0: 루트(팀스페이스 직속), depth=1 이하: 하위 페이지

with recursive page_hierarchy as (
    -- 앵커: 루트 레벨 페이지
    select
        page_id,
        page_title,
        parent_id,
        page_title as breadcrumb_path,
        0 as depth,
        case
            when lower(page_title) like '%마케팅%'
                or lower(page_title) like '%onboarding%' 
                or lower(page_title) like '%프로젝트%' then 'marketing'
            when lower(page_title) = 'NNT Tech' then 'tech'
            when lower(page_title) = 'NNT Tools' then 'tools'
            else 'uncategorized'
        end as category,
        cast(null as string) as client_name,
        notion_url,
        last_edited_at
    from {{ ref('stg_notion_pages') }}
    where parent_type = 'workspace'
       or parent_id is null

    union all

    -- 재귀: 자식 페이지
    select
        child.page_id,
        child.page_title,
        child.parent_id,
        concat(parent.breadcrumb_path, ' > ', child.page_title) as breadcrumb_path,
        parent.depth + 1,
        parent.category,
        case
            when parent.depth = 0 then child.page_title  -- depth=1의 자식 → 고객사
            else parent.client_name
        end as client_name,
        child.notion_url,
        child.last_edited_at
    from {{ ref('stg_notion_pages') }} child
    inner join page_hierarchy parent
        on child.parent_id = parent.page_id
    where parent.depth < 10  -- 무한 루프 방지
)

select * from page_hierarchy
