"""Local re-ranking of paper search hits using title + abstract embeddings."""

from __future__ import annotations

import logging
import math
import re

from app.db.models import Paper

logger = logging.getLogger(__name__)

# Weights for combining title / abstract cosine similarity
TITLE_WEIGHT = 0.4
ABSTRACT_WEIGHT = 0.6
# Soft bonus when query terms appear in title or abstract (lexical overlap)
LEXICAL_BONUS = 0.08


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return float(dot / (math.sqrt(na) * math.sqrt(nb)))


def _paper_doc(paper: Paper) -> tuple[str, str]:
    title = (paper.title or "").strip()
    abstract = (paper.abstract or "").strip()
    return title, abstract


def _query_terms(query: str) -> list[str]:
    return [t.lower() for t in re.split(r"\s+", query.strip()) if len(t) > 1]


def _lexical_overlap(query: str, title: str, abstract: str) -> float:
    terms = _query_terms(query)
    if not terms:
        return 0.0
    blob = f"{title} {abstract}".lower()
    hit = sum(1 for t in terms if t in blob)
    return hit / len(terms)


def rerank_papers(query: str, papers: list[Paper], top_k: int) -> list[Paper]:
    """
    Re-rank by embedding similarity on title and abstract jointly.
    Falls back to original order if embeddings fail or papers lack text.
    """
    if not papers or top_k <= 0:
        return []
    if len(papers) == 1:
        return papers[:top_k]

    try:
        from app.index.embedder import get_embeddings

        emb = get_embeddings()
        q_vec = emb.embed_query(query.strip())

        titles: list[str] = []
        abstracts: list[str] = []
        for p in papers:
            title, abstract = _paper_doc(p)
            titles.append(title or p.paper_id)
            # Prefer abstract; if missing, reuse title so vector still exists
            abstracts.append(abstract or title or p.paper_id)

        title_vecs = emb.embed_documents(titles)
        abs_vecs = emb.embed_documents(abstracts)

        scored: list[tuple[float, int]] = []
        for i, p in enumerate(papers):
            title, abstract = _paper_doc(p)
            s_title = _cosine(q_vec, title_vecs[i])
            s_abs = _cosine(q_vec, abs_vecs[i])
            # If no abstract, lean more on title
            if not abstract:
                score = s_title
            else:
                score = TITLE_WEIGHT * s_title + ABSTRACT_WEIGHT * s_abs
            score += LEXICAL_BONUS * _lexical_overlap(query, title, abstract)
            scored.append((score, i))

        scored.sort(key=lambda x: x[0], reverse=True)
        preview = [
            (round(s, 3), (papers[i].title or "")[:40])
            for s, i in scored[: min(5, len(scored))]
        ]
        logger.info("rerank query=%r top=%s", query[:80], preview)
        return [papers[i] for _, i in scored[:top_k]]
    except Exception:
        logger.warning("paper rerank failed; keeping API order", exc_info=True)
        return papers[:top_k]
