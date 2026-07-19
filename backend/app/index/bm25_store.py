import re
import threading
from typing import Any, Optional

from rank_bm25 import BM25Okapi

from app.db import sqlite as db

_cache: dict[str, Any] = {
    "bm25": None,
    "docs": [],
}
_cache_lock = threading.RLock()


def _tokenize(text: str) -> list[str]:
    """Tokenize Latin words and CJK text without an external tokenizer."""
    lowered = (text or "").lower()
    tokens = re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", lowered)
    for segment in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]+", lowered):
        tokens.extend(segment)
        tokens.extend(segment[i : i + 2] for i in range(len(segment) - 1))
    return tokens


def rebuild_bm25_index() -> None:
    rows = db.list_all_chunks()
    docs = [
        {
            "chunk_id": r["chunk_id"],
            "paper_id": r["paper_id"],
            "title": r["title"],
            "year": r["year"],
            "text": r["text"],
        }
        for r in rows
    ]
    bm25 = None
    if docs:
        corpus = [_tokenize(d["text"]) or ["__empty__"] for d in docs]
        bm25 = BM25Okapi(corpus)
    with _cache_lock:
        _cache["bm25"] = bm25
        _cache["docs"] = docs


def invalidate_bm25_index() -> None:
    with _cache_lock:
        _cache["bm25"] = None
        _cache["docs"] = []


def sparse_search(
    query: str,
    top_k: int = 10,
    allowed_paper_ids: Optional[set[str] | list[str]] = None,
) -> list[dict[str, Any]]:
    if allowed_paper_ids is not None and not allowed_paper_ids:
        return []
    with _cache_lock:
        needs_rebuild = _cache["bm25"] is None or not _cache["docs"]
    if needs_rebuild:
        rebuild_bm25_index()
    with _cache_lock:
        bm25 = _cache["bm25"]
        docs = _cache["docs"]
    if bm25 is None or not docs:
        return []

    scores = bm25.get_scores(_tokenize(query))
    allowed = set(allowed_paper_ids) if allowed_paper_ids is not None else None
    candidates = (
        (idx, score)
        for idx, score in enumerate(scores)
        if allowed is None or docs[idx]["paper_id"] in allowed
    )
    ranked = sorted(
        candidates,
        key=lambda x: x[1],
        reverse=True,
    )[:top_k]

    hits: list[dict[str, Any]] = []
    for idx, score in ranked:
        if score <= 0:
            continue
        doc = docs[idx]
        hits.append(
            {
                "chunk_id": doc["chunk_id"],
                "paper_id": doc["paper_id"],
                "title": doc["title"],
                "year": doc["year"],
                "text": doc["text"],
                "score": float(score),
            }
        )
    return hits
