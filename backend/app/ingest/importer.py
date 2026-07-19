import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from app.core.config import get_settings
from app.db import sqlite as db
from app.db.models import Paper
from app.index.bm25_store import rebuild_bm25_index
from app.index.pipeline import index_paper
from app.ingest.pdf_fetch import fetch_pdf_text
from app.ingest.textutil import sanitize_text

logger = logging.getLogger(__name__)

# on_progress(current_index_1based, total, title, stage, message)
ImportProgressCallback = Callable[[int, int, str, str, str], None]


def _short_title(title: str, limit: int = 48) -> str:
    t = sanitize_text(title or "").strip()
    return t if len(t) <= limit else t[: limit - 1] + "…"


def _resolve_full_text(paper: Paper, provided: Optional[str]) -> tuple[str | None, str]:
    """
    Returns (text, source_label).
    Prefer explicit full_text → PDF → abstract.
    """
    if provided and provided.strip():
        return provided.strip(), "provided"

    pdf_text = fetch_pdf_text(paper)
    if pdf_text:
        return pdf_text, "pdf"

    abstract = (paper.abstract or "").strip()
    if abstract:
        return abstract, "abstract"

    title = (paper.title or "").strip()
    return (title or None), "title"


def import_papers(
    papers: list[Paper],
    folder_id: Optional[str] = None,
    full_texts: Optional[dict[str, str]] = None,
    on_progress: Optional[ImportProgressCallback] = None,
) -> list[str]:
    """
    Batch import with parallel PDF fetch, then sequential index.
    BM25 is rebuilt once at the end (not per paper).
    """
    full_texts = full_texts or {}
    total = len(papers)
    if total == 0:
        return []

    settings = get_settings()
    workers = max(1, min(settings.import_concurrency, total))

    for paper in papers:
        if folder_id:
            paper.folder_id = folder_id

    if on_progress:
        on_progress(
            0,
            total,
            "",
            "fetch",
            f"并行拉取全文（最多 {workers} 路）…",
        )

    resolved: dict[str, tuple[str | None, str]] = {}
    fetch_done = 0

    def _fetch(paper: Paper) -> tuple[str, str | None, str]:
        text, source = _resolve_full_text(paper, full_texts.get(paper.paper_id))
        return paper.paper_id, text, source

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch, p): p for p in papers}
        for fut in as_completed(futures):
            paper = futures[fut]
            title = (paper.title or paper.paper_id).strip()
            try:
                pid, text, source = fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("fetch failed %s: %s", paper.paper_id, exc)
                pid = paper.paper_id
                text = (paper.abstract or paper.title or "").strip() or None
                source = "abstract" if paper.abstract else "title"
            resolved[pid] = (text, source)
            fetch_done += 1
            if on_progress:
                on_progress(
                    fetch_done,
                    total,
                    title,
                    "fetch",
                    f"拉取完成 {fetch_done}/{total}：{_short_title(title)}（{source}）",
                )

    imported_ids: list[str] = []
    for i, paper in enumerate(papers, start=1):
        title = (paper.title or paper.paper_id).strip()
        short = _short_title(title)
        text, source = resolved.get(paper.paper_id, (None, "title"))
        if on_progress:
            on_progress(i, total, title, "index", f"({i}/{total}) 建立索引（{source}）…")
        n_chunks = index_paper(paper, full_text=text, refresh_bm25=False)
        logger.info(
            "Indexed %s via %s (%s chunks, %s chars)",
            paper.paper_id,
            source,
            n_chunks,
            len(text or ""),
        )
        imported_ids.append(paper.paper_id)
        if on_progress:
            on_progress(i, total, title, "done", f"({i}/{total}) 已完成：{short}")

    if on_progress:
        on_progress(total, total, "", "bm25", "正在刷新检索索引…")
    rebuild_bm25_index()
    return imported_ids


def enrich_papers_with_pdf(paper_ids: Optional[list[str]] = None) -> dict:
    """
    Re-download PDFs for existing library papers and rebuild their indexes.
    If paper_ids is None/empty, process the whole library.
    """
    papers = db.list_papers()
    if paper_ids:
        wanted = set(paper_ids)
        papers = [p for p in papers if p.paper_id in wanted]

    enriched = 0
    skipped = 0
    failed = 0
    details: list[dict] = []

    settings = get_settings()
    workers = max(1, min(settings.import_concurrency, len(papers) or 1))

    def _fetch(paper: Paper) -> tuple[Paper, str | None]:
        return paper, fetch_pdf_text(paper)

    fetched: list[tuple[Paper, str | None]] = []
    if papers:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            fetched = list(pool.map(_fetch, papers))

    for paper, text in fetched:
        if not text:
            skipped += 1
            details.append({"paper_id": paper.paper_id, "status": "no_pdf"})
            continue
        abstract_len = len((paper.abstract or "").strip())
        # Only reindex when PDF clearly adds more than abstract-only
        if len(text) < max(abstract_len + 200, 500):
            skipped += 1
            details.append({"paper_id": paper.paper_id, "status": "too_short"})
            continue
        try:
            n_chunks = index_paper(paper, full_text=text, refresh_bm25=False)
            enriched += 1
            details.append(
                {
                    "paper_id": paper.paper_id,
                    "status": "ok",
                    "chars": len(text),
                    "chunks": n_chunks,
                }
            )
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.warning("enrich failed %s: %s", paper.paper_id, exc)
            details.append({"paper_id": paper.paper_id, "status": "error", "error": str(exc)})

    if enriched:
        rebuild_bm25_index()

    return {
        "enriched": enriched,
        "skipped": skipped,
        "failed": failed,
        "details": details,
    }
