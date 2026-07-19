from collections import defaultdict
from typing import Any, Optional


def _normalize_year(year: Any) -> Optional[int]:
    if year is None or year == "" or year == -1:
        return None
    try:
        return int(year)
    except (TypeError, ValueError):
        return None


def rrf_fuse(
    dense_hits: list[dict[str, Any]],
    sparse_hits: list[dict[str, Any]],
    top_k: int = 6,
    k: int = 60,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion over chunk_id."""
    scores: dict[str, float] = defaultdict(float)
    payload: dict[str, dict[str, Any]] = {}

    for rank, hit in enumerate(dense_hits):
        cid = hit["chunk_id"]
        scores[cid] += 1.0 / (k + rank + 1)
        payload[cid] = hit

    for rank, hit in enumerate(sparse_hits):
        cid = hit["chunk_id"]
        scores[cid] += 1.0 / (k + rank + 1)
        # Prefer denser metadata if already present
        if cid not in payload:
            payload[cid] = hit

    ranked_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:top_k]
    fused: list[dict[str, Any]] = []
    for cid in ranked_ids:
        item = dict(payload[cid])
        item["score"] = scores[cid]
        item["year"] = _normalize_year(item.get("year"))
        fused.append(item)
    return fused


def _chunks_as_hits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        hits.append(
            {
                "chunk_id": r["chunk_id"],
                "paper_id": r["paper_id"],
                "title": r.get("title") or "",
                "year": _normalize_year(r.get("year")),
                "text": r.get("text") or "",
                "score": 1.0 / (i + 1),
            }
        )
    return hits


def diversify_by_paper(
    hits: list[dict[str, Any]],
    top_k: int,
    preferred_paper_ids: Optional[set[str] | list[str]] = None,
) -> list[dict[str, Any]]:
    """Round-robin across papers so multi-paper survey/compare is not one-sided."""
    if not hits or top_k <= 0:
        return []
    by_paper: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for h in hits:
        pid = h.get("paper_id") or ""
        if pid:
            by_paper[pid].append(h)
    if not by_paper:
        return hits[:top_k]

    if isinstance(preferred_paper_ids, set):
        preferred = sorted(preferred_paper_ids)
    else:
        preferred = list(dict.fromkeys(preferred_paper_ids or []))
    order = [p for p in preferred if p in by_paper]
    order.extend(p for p in by_paper if p not in order)

    out: list[dict[str, Any]] = []
    cursor = {p: 0 for p in by_paper}
    while len(out) < top_k:
        progressed = False
        for pid in order:
            i = cursor[pid]
            bucket = by_paper[pid]
            if i < len(bucket):
                out.append(bucket[i])
                cursor[pid] = i + 1
                progressed = True
                if len(out) >= top_k:
                    break
        if not progressed:
            break
    return out


def hybrid_search(
    query: str,
    top_k: int = 6,
    allowed_paper_ids: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    from app.db import sqlite as db
    from app.index.bm25_store import sparse_search
    from app.index.vector_store import dense_search

    if allowed_paper_ids is not None and not allowed_paper_ids:
        return []

    candidate_k = max(top_k * 4, 12)
    if allowed_paper_ids is not None:
        candidate_k = max(candidate_k, min(len(allowed_paper_ids) * 4, 200))

    dense = dense_search(
        query,
        top_k=candidate_k,
        allowed_paper_ids=allowed_paper_ids,
    )
    sparse = sparse_search(
        query,
        top_k=candidate_k,
        allowed_paper_ids=allowed_paper_ids,
    )

    fuse_k = top_k
    if allowed_paper_ids is not None and len(allowed_paper_ids) > 1:
        fuse_k = max(top_k * 3, len(allowed_paper_ids) * 6)
    fused = rrf_fuse(dense, sparse, top_k=max(fuse_k, candidate_k))
    if allowed_paper_ids is not None:
        if len(allowed_paper_ids) > top_k and fused:
            # Full coverage is impossible when the scope is larger than top_k.
            # Preserve relevance order instead of favoring arbitrary paper IDs.
            return diversify_by_paper(fused, top_k)
        # Append one or more fallback chunks per selected paper. Relevance-ranked
        # chunks stay first inside each paper bucket, while explicit scope is not lost.
        scoped_rows = db.list_chunks_for_papers(
            allowed_paper_ids,
            limit=max(candidate_k, len(allowed_paper_ids)),
        )
        seen = {h.get("chunk_id") for h in fused}
        fused.extend(
            h for h in _chunks_as_hits(scoped_rows) if h.get("chunk_id") not in seen
        )
        return diversify_by_paper(fused, top_k, allowed_paper_ids)

    return fused[:top_k]
