{{
    config(
        materialized='view'
    )
}}

-- 노션과 슬랙 청크를 통합하는 UNION ALL view.
-- 임베딩 파이프라인이 이 view를 읽어 벡터를 생성한다.

select
    chunk_id,
    page_id,
    page_title,
    breadcrumb_path,
    category,
    is_onboarding,
    notion_url,
    client_name,
    tags,
    chunk_text,
    section_number,
    last_edited_at,
    chunk_length,
    'notion' as source_type
from {{ ref('mart_notion_chunks') }}

union all

select
    chunk_id,
    page_id,
    page_title,
    breadcrumb_path,
    category,
    is_onboarding,
    notion_url,
    client_name,
    tags,
    chunk_text,
    section_number,
    last_edited_at,
    chunk_length,
    'slack' as source_type
from {{ ref('mart_slack_chunks') }}
