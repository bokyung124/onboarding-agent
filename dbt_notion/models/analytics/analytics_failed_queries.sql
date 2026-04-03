{{
    config(
        materialized='view'
    )
}}

-- 최근 7일간 실패 쿼리 (chunks_retrieved=0 또는 success=false)

select
    query,
    category,
    count(*) as fail_count,
    cast(avg(latency_ms) as int64) as avg_latency_ms,
    min(timestamp) as first_seen,
    max(timestamp) as last_seen
from {{ source('analytics', 'analytics_search_logs') }}
where timestamp >= timestamp_sub(current_timestamp(), interval 7 day)
  and (success = false or chunks_retrieved = 0)
group by query, category
order by fail_count desc
limit 50
