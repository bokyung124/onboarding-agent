"""사용자 쿼리 텍스트를 Gemini 임베딩 벡터로 변환한다."""

from google import genai


class EmbedderService:
    def __init__(self, client: genai.Client, model: str = "gemini-embedding-2-preview"):
        self._client = client
        self._model = model

    def embed_query(self, text: str) -> list[float]:
        """쿼리 텍스트를 768차원 벡터로 변환한다."""
        response = self._client.models.embed_content(
            model=self._model,
            contents=text,
        )
        return response.embeddings[0].values
