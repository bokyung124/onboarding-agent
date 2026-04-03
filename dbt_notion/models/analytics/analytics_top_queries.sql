{{
    config(
        materialized='view'
    )
}}

-- 최근 7일간 빈도순 상위 쿼리 TOP 50

select
    query,
    category,
    count(*) as query_count,
    cast(avg(latency_ms) as int64) as avg_latency_ms,
    round(avg(chunks_retrieved), 1) as avg_chunks,
    min(timestamp) as first_seen,
    max(timestamp) as last_seen
from {{ source('analytics', 'analytics_search_logs') }}
where timestamp >= timestamp_sub(current_timestamp(), interval 7 day)
group by query, category
order by query_count desc
limit 50
