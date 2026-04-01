{{
    config(
        materialized='view'
    )
}}

-- 최근 7일간 카테고리별 검색 통계

select
    category,
    count(*) as search_count,
    countif(is_onboarding = true) as onboarding_count,
    cast(avg(latency_ms) as int64) as avg_latency_ms,
    round(avg(chunks_retrieved), 1) as avg_chunks,
    round(avg(sources_count), 1) as avg_sources,
    round(countif(success = true and chunks_retrieved > 0) * 100.0 / count(*), 1) as success_rate
from `{{ env_var("GCP_PROJECT_ID") }}.{{ env_var("BQ_DATASET", "onboarding_agent") }}.analytics_search_logs`
where timestamp >= timestamp_sub(current_timestamp(), interval 7 day)
group by category
order by search_count desc
