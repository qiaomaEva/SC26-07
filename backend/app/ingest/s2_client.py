from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.db.models import Paper

S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "paperId,title,abstract,year,authors,url,externalIds,openAccessPdf"


def _headers() -> dict[str, str]:
    settings = get_settings()
    headers = {"Accept": "application/json"}
    if settings.semantic_scholar_api_key:
        headers["x-api-key"] = settings.semantic_scholar_api_key
    return headers


def _parse_year(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _to_paper(item: dict[str, Any]) -> Optional[Paper]:
    paper_id = item.get("paperId")
    title = (item.get("title") or "").strip()
    if not paper_id or not title:
        return None
    authors = [
        a.get("name", "").strip()
        for a in (item.get("authors") or [])
        if a.get("name")
    ]
    url = item.get("url") or f"https://www.semanticscholar.org/paper/{paper_id}"
    ext = item.get("externalIds") or {}
    arxiv_id = (ext.get("ArXiv") or "").strip()
    oa = item.get("openAccessPdf") or {}
    pdf_url = (oa.get("url") or "").strip() or None

    # Prefer arXiv id so PDF download / dedup is stable
    if arxiv_id:
        return Paper(
            paper_id=f"arxiv:{arxiv_id}",
            title=title,
            authors=authors,
            year=_parse_year(item.get("year")),
            abstract=item.get("abstract"),
            url=f"https://arxiv.org/abs/{arxiv_id}",
            pdf_url=pdf_url or f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            source="semanticscholar",
        )

    return Paper(
        paper_id=str(paper_id),
        title=title,
        authors=authors,
        year=_parse_year(item.get("year")),
        abstract=item.get("abstract"),
        url=url,
        pdf_url=pdf_url,
        source="semanticscholar",
    )


async def search_papers(query: str, limit: int = 10) -> list[Paper]:
    params = {
        "query": query,
        "limit": limit,
        "fields": FIELDS,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(S2_SEARCH_URL, params=params, headers=_headers())
        resp.raise_for_status()
        data = resp.json()

    papers: list[Paper] = []
    for item in data.get("data") or []:
        paper = _to_paper(item)
        if paper:
            papers.append(paper)
    return papers
