from pydantic import BaseModel


class ChunkResult(BaseModel):
    chunk_id: str
    page_id: str
    page_title: str
    breadcrumb: str
    category: str
    content: str
    source_url: str
    source_type: str = "notion"
    distance: float
