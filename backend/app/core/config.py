from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Chat (DeepSeek / any OpenAI-compatible chat API)
    openai_api_key: str = ""
    openai_api_base: str = "https://api.deepseek.com"
    openai_chat_model: str = "deepseek-chat"
    openai_timeout_seconds: float = Field(default=30, ge=5, le=300)

    # Embedding: DeepSeek has no embeddings endpoint → default local
    embedding_provider: str = "local"  # local | openai_compatible
    embedding_api_key: str = ""
    embedding_api_base: str = "https://api.openai.com/v1"
    openai_embedding_model: str = "text-embedding-3-small"

    semantic_scholar_api_key: str = ""
    # auto | semanticscholar | arxiv
    # auto: try Semantic Scholar first, fall back to arXiv on 429
    paper_search_source: str = "auto"
    # Local re-rank of online hits by title+abstract embedding similarity
    search_rerank: bool = True
    search_candidate_pool: int = 24

    app_host: str = "127.0.0.1"
    app_port: int = 8888
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    sqlite_path: str = "./data/app.db"
    chroma_path: str = "./data/chroma"

    chunk_size: int = 900
    chunk_overlap: int = 150
    default_top_k: int = 8

    # Literature survey pipeline (literature-review skill)
    survey_pipeline: bool = True
    survey_personas: int = 3
    survey_queries_per_persona: int = 2
    survey_persona_top_k: int = 6

    # Full-paper RAG: download open-access PDF on import when possible
    fetch_pdf_on_import: bool = True
    pdf_max_chars: int = 200_000
    pdf_upload_max_bytes: int = Field(
        default=30 * 1024 * 1024,
        ge=1024,
        le=200 * 1024 * 1024,
    )
    # Parallel PDF download/extract workers during batch import
    import_concurrency: int = 3
    # Per-mirror read timeout; try next mirror on failure (keep fetching PDF)
    pdf_fetch_timeout: float = 35.0
    pdf_fetch_retries: int = 2

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sqlite_abs_path(self) -> Path:
        path = Path(self.sqlite_path)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def chroma_abs_path(self) -> Path:
        path = Path(self.chroma_path)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()
