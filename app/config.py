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
    gemini_embedding_model: str = "gemini-embedding-2-preview"

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
    search_distance_threshold: float = 0.7

    # 검색 타임아웃
    search_timeout_seconds: float = 30.0

    # 캐시
    cache_ttl_seconds: int = 3600
    cache_max_size: int = 500
