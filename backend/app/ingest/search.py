"""Unified paper search with Semantic Scholar + arXiv fallback + local rerank."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

import httpx

from app.core.config import get_settings
from app.db.models import Paper
from app.ingest import arxiv_client, s2_client
from app.ingest.rerank import rerank_papers
from app.index.embedder import local_embedding_model_cached

logger = logging.getLogger(__name__)
SearchProgressCallback = Callable[[str, str], None]


def _notify(
    callback: Optional[SearchProgressCallback], message: str, step: str
) -> None:
    if callback is not None:
        callback(message, step)


async def _search_s2_with_retry(
    query: str,
    limit: int,
    retries: int = 2,
    on_progress: Optional[SearchProgressCallback] = None,
) -> list[Paper]:
    last_exc: Exception | None = None
    has_api_key = bool(get_settings().semantic_scholar_api_key)
    for attempt in range(retries + 1):
        try:
            return await s2_client.search_papers(query, limit=limit)
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            status = exc.response.status_code
            if status == 429 and has_api_key and attempt < retries:
                wait = 1.5 * (attempt + 1)
                logger.warning("S2 rate limited (429), retry in %.1fs", wait)
                _notify(
                    on_progress,
                    f"Semantic Scholar 请求受限，{wait:.1f} 秒后重试…\n检索词：{query}",
                    "search_source",
                )
                await asyncio.sleep(wait)
                continue
            raise
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < retries:
                await asyncio.sleep(1.0 * (attempt + 1))
                continue
            raise
    assert last_exc is not None
    raise last_exc


async def _fetch_candidates(
    query: str,
    limit: int,
    on_progress: Optional[SearchProgressCallback] = None,
) -> list[Paper]:
    settings = get_settings()
    source = (settings.paper_search_source or "auto").strip().lower()

    if source == "arxiv":
        _notify(
            on_progress,
            f"正在查询 arXiv…\n检索词：{query}",
            "search_source",
        )
        try:
            return await arxiv_client.search_papers(query, limit=limit)
        except Exception:
            logger.warning("arXiv failed, trying Semantic Scholar", exc_info=True)
            _notify(
                on_progress,
                f"arXiv 暂不可用，正在切换 Semantic Scholar…\n检索词：{query}",
                "search_source",
            )
            return await _search_s2_with_retry(
                query, limit=limit, on_progress=on_progress
            )

    if source == "semanticscholar":
        _notify(
            on_progress,
            f"正在查询 Semantic Scholar…\n检索词：{query}",
            "search_source",
        )
        try:
            return await _search_s2_with_retry(
                query, limit=limit, on_progress=on_progress
            )
        except Exception:
            logger.warning("Semantic Scholar failed, trying arXiv", exc_info=True)
            _notify(
                on_progress,
                f"Semantic Scholar 暂不可用，正在切换 arXiv…\n检索词：{query}",
                "search_source",
            )
            return await arxiv_client.search_papers(query, limit=limit)

    # auto: S2 first, arXiv backup
    _notify(
        on_progress,
        f"正在查询 Semantic Scholar…\n检索词：{query}",
        "search_source",
    )
    try:
        return await _search_s2_with_retry(
            query, limit=limit, on_progress=on_progress
        )
    except Exception:
        logger.warning("Semantic Scholar failed → fallback to arXiv", exc_info=True)
        _notify(
            on_progress,
            f"Semantic Scholar 暂不可用，正在切换 arXiv…\n检索词：{query}",
            "search_source",
        )
        return await arxiv_client.search_papers(query, limit=limit)


async def search_papers(
    query: str,
    limit: int = 10,
    on_progress: Optional[SearchProgressCallback] = None,
) -> list[Paper]:
    """
    Online search then local re-rank by title + abstract similarity.
    Fetches a larger candidate pool so rerank has room to promote abstract-matched papers.
    """
    q = (query or "").strip()
    if not q:
        return []

    settings = get_settings()
    # Pull more candidates, then cut to `limit` after title+abstract rerank
    pool = max(limit, min(settings.search_candidate_pool, max(limit * 3, 24)))
    candidates = await _fetch_candidates(q, pool, on_progress=on_progress)
    if not candidates:
        return []

    # Deduplicate by paper_id / arxiv id while preserving order
    seen: set[str] = set()
    unique: list[Paper] = []
    for p in candidates:
        if p.paper_id in seen:
            continue
        seen.add(p.paper_id)
        unique.append(p)

    if not settings.search_rerank:
        return unique[:limit]

    embedding_provider = (settings.embedding_provider or "local").strip().lower()
    if embedding_provider == "local" and not local_embedding_model_cached():
        _notify(
            on_progress,
            f"正在返回检索结果…\n候选：{len(unique)} 篇 · 使用论文源相关性排序",
            "rerank",
        )
        return unique[:limit]

    _notify(
        on_progress,
        f"正在整理候选论文…\n候选：{len(unique)} 篇 · 按标题与摘要相关性排序",
        "rerank",
    )
    return await asyncio.to_thread(rerank_papers, q, unique, limit)
