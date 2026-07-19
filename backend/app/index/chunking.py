from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import get_settings


def get_splitter(
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> RecursiveCharacterTextSplitter:
    settings = get_settings()
    size = max(32, chunk_size or settings.chunk_size)
    overlap = min(max(0, chunk_overlap if chunk_overlap is not None else settings.chunk_overlap), size - 1)
    return RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=[
            "\n\n",
            "\n",
            "。",
            "！",
            "？",
            "；",
            ". ",
            "! ",
            "? ",
            "; ",
            "，",
            ", ",
            " ",
            "",
        ],
    )


def chunk_text(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    settings = get_settings()
    cjk_chars = sum("\u3400" <= char <= "\u9fff" for char in text)
    cjk_heavy = cjk_chars / len(text) >= 0.25
    if cjk_heavy and (settings.embedding_provider or "local").lower() == "local":
        # Chroma's local MiniLM accepts at most 256 wordpiece tokens. CJK text
        # is much closer to one token per character than English prose.
        return get_splitter(
            chunk_size=min(settings.chunk_size, 220),
            chunk_overlap=min(settings.chunk_overlap, 40),
        ).split_text(text)
    return get_splitter().split_text(text)
