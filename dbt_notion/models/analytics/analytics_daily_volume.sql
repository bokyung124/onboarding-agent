{{
    config(
        materialized='view'
    )
}}

-- 최근 30일간 일별 검색 건수 추이

select
    date(timestamp) as search_date,
    count(*) as total_searches,
    countif(success = true and chunks_retrieved > 0) as successful_searches,
    countif(success = false or chunks_retrieved = 0) as failed_searches,
    cast(avg(latency_ms) as int64) as avg_latency_ms
from `{{ env_var("GCP_PROJECT_ID") }}.{{ env_var("BQ_DATASET", "onboarding_agent") }}.analytics_search_logs`
where timestamp >= timestamp_sub(current_timestamp(), interval 30 day)
group by search_date
order by search_date desc
