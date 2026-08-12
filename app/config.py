from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # GCP / BigQuery
    gcp_project_id: str
    bq_dataset: str = "onboarding_agent"
    bq_vectors_table: str = "mart_enterprise_vectors"

    @property
    def bq_mart_dataset(self) -> str:
        """서빙 레이어에서 사용하는 mart 데이터셋."""
        return f"{self.bq_dataset}_mart_notion"

    # Gemini (답변 생성 + 임베딩)
    gemini_api_key: str
    gemini_model: str = "gemini-3-flash-preview"
    gemini_embedding_model: str = "gemini-embedding-2"

    # Notion (파이프라인 전용, 서빙에서는 미사용)
    notion_api_key: str = ""
    notion_root_page_id: str = ""

    # Slack
    slack_bot_token: str = ""
    slack_app_token: str = ""  # Socket Mode용 (xapp-...)
    slack_channel_ids: str = ""
    slack_workspace: str = ""

    # 검색 설정
    search_top_k: int = 50
    search_result_limit: int = 8
    search_distance_threshold: float = 0.85
    search_fraction_lists: float = 0.3  # IVF 인덱스 recall 튜닝 (0.0~1.0)
    reranker_enabled: bool = True

    # 검색 타임아웃
    search_timeout_seconds: float = 60.0
    slack_search_timeout_seconds: float = 120.0

    # 캐시
    cache_ttl_seconds: int = 3600
    cache_max_size: int = 500

    # 체크리스트
    checklist_cache_ttl_seconds: int = 86400
    checklist_cache_max_size: int = 20
    checklist_top_k: int = 80
    checklist_result_limit: int = 15

    # 대화 맥락 (Multi-turn)
    conversation_cache_ttl_seconds: int = 3600
    conversation_cache_max_size: int = 200
    conversation_max_turns: int = 5

    # 멀티스텝 에이전트
    multi_step_enabled: bool = True
    multi_step_max_sub_queries: int = 3

    # 자기 검증 (Reflection)
    reflection_enabled: bool = True
    reflection_distance_threshold: float = 0.65
    reflection_min_chunks: int = 2

    # 대시보드 인증
    dashboard_password: str = ""
