from functools import lru_cache
from pathlib import Path
from typing import Protocol

from langchain_openai import OpenAIEmbeddings

from app.core.config import get_settings


class Embeddings(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class LocalChromaEmbeddings:
    """Local MiniLM embeddings via Chroma's default ONNX model (no API key)."""

    def __init__(self) -> None:
        from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import (
            ONNXMiniLM_L6_V2,
        )

        self._ef = ONNXMiniLM_L6_V2()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._ef(texts)
        return [list(map(float, v)) for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def local_embedding_model_cached() -> bool:
    """Check the Chroma MiniLM files without triggering its 79 MB download."""
    try:
        from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import (
            ONNXMiniLM_L6_V2,
        )
        download_path = ONNXMiniLM_L6_V2.DOWNLOAD_PATH
        extracted_folder = ONNXMiniLM_L6_V2.EXTRACTED_FOLDER_NAME
    except (ImportError, AttributeError):
        return False

    model_dir = Path(download_path) / extracted_folder
    required_files = (
        "config.json",
        "model.onnx",
        "special_tokens_map.json",
        "tokenizer_config.json",
        "tokenizer.json",
        "vocab.txt",
    )
    return all((model_dir / name).is_file() for name in required_files)


def embedding_status() -> dict[str, str | bool]:
    settings = get_settings()
    provider = (settings.embedding_provider or "local").strip().lower()
    if provider == "local":
        ready = local_embedding_model_cached()
        return {
            "provider": provider,
            "model": "all-MiniLM-L6-v2",
            "ready": ready,
            "requires_initialization": not ready,
        }
    if provider == "openai_compatible":
        configured = bool(settings.embedding_api_key or settings.openai_api_key)
        return {
            "provider": provider,
            "model": settings.openai_embedding_model,
            "ready": configured,
            "requires_initialization": False,
        }
    return {
        "provider": provider,
        "model": "",
        "ready": False,
        "requires_initialization": False,
    }


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    settings = get_settings()
    provider = (settings.embedding_provider or "local").strip().lower()

    if provider == "local":
        return LocalChromaEmbeddings()

    if provider == "openai_compatible":
        api_key = settings.embedding_api_key or settings.openai_api_key
        if not api_key:
            raise RuntimeError(
                "EMBEDDING_API_KEY (or OPENAI_API_KEY) is missing for openai_compatible embeddings."
            )
        return OpenAIEmbeddings(
            api_key=api_key,
            base_url=settings.embedding_api_base,
            model=settings.openai_embedding_model,
        )

    raise RuntimeError(
        f"Unknown EMBEDDING_PROVIDER={settings.embedding_provider!r}. "
        "Use 'local' or 'openai_compatible'."
    )
