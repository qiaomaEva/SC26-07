import threading

from app.db import sqlite as db
from app.db.models import Paper
from app.index.bm25_store import invalidate_bm25_index, rebuild_bm25_index
from app.index.chunking import chunk_text
from app.index.vector_store import (
    embed_documents,
    replace_paper_vectors,
    restore_paper_vectors,
    sanitize_metadata,
)
from app.ingest.textutil import sanitize_text

_index_write_lock = threading.RLock()


def index_paper(
    paper: Paper,
    full_text: str | None = None,
    *,
    refresh_bm25: bool = True,
) -> int:
    """Chunk abstract/full_text, write SQLite chunks + Chroma vectors, refresh BM25."""
    source_text = sanitize_text(full_text or paper.abstract or "").strip()
    if not source_text:
        source_text = sanitize_text(paper.title)

    parts = chunk_text(source_text)
    if not parts:
        parts = [source_text]

    chunk_rows: list[tuple[str, str, int, int]] = []
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    for idx, text in enumerate(parts):
        chunk_id = f"{paper.paper_id}::{idx}"
        token_est = max(1, len(text) // 4)
        chunk_rows.append((chunk_id, text, idx, token_est))
        ids.append(chunk_id)
        documents.append(text)
        metadatas.append(
            sanitize_metadata(
                {
                    "paper_id": paper.paper_id,
                    "title": paper.title,
                    "year": paper.year,
                    "chunk_index": idx,
                }
            )
        )

    # Fail before touching persisted state when embedding is unavailable.
    embeddings = embed_documents(documents)
    with _index_write_lock:
        vector_snapshot = replace_paper_vectors(
            paper.paper_id,
            ids,
            documents,
            metadatas,
            embeddings,
        )
        try:
            db.upsert_paper_and_replace_chunks(paper, chunk_rows)
        except Exception:
            restore_paper_vectors(paper.paper_id, vector_snapshot)
            raise

        invalidate_bm25_index()
        if refresh_bm25:
            rebuild_bm25_index()
    return len(parts)
