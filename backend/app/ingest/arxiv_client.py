"""arXiv search fallback (no API key, more generous for demos)."""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import quote_plus

import httpx

from app.db.models import Paper

logger = logging.getLogger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _text(el: Optional[ET.Element]) -> str:
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _arxiv_id_from_url(url: str) -> str:
    m = re.search(r"arxiv\.org/abs/([^/\s]+)", url)
    if not m:
        return url.rsplit("/", 1)[-1]
    return re.sub(r"v\d+$", "", m.group(1))


def _parse_year(published: str) -> Optional[int]:
    if len(published) >= 4 and published[:4].isdigit():
        return int(published[:4])
    return None


def _build_search_query(query: str) -> str:
    """
    Search title AND abstract (not title-only).
    For each term: (ti:term OR abs:term), combined with AND across terms.
    """
    terms = [t for t in re.split(r"\s+", query.strip()) if t]
    if not terms:
        return "all:machine"
    parts: list[str] = []
    for t in terms:
        safe = t.replace('"', "")
        parts.append(f'(ti:"{safe}" OR abs:"{safe}")')
    return " AND ".join(parts)


def _parse_feed(xml_text: str) -> list[Paper]:
    root = ET.fromstring(xml_text)
    papers: list[Paper] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        title = re.sub(r"\s+", " ", _text(entry.find("atom:title", ATOM_NS)))
        summary = re.sub(r"\s+", " ", _text(entry.find("atom:summary", ATOM_NS)))
        published = _text(entry.find("atom:published", ATOM_NS))
        id_url = _text(entry.find("atom:id", ATOM_NS))
        if not title or not id_url:
            continue
        arxiv_id = _arxiv_id_from_url(id_url)
        authors = [
            _text(a.find("atom:name", ATOM_NS))
            for a in entry.findall("atom:author", ATOM_NS)
        ]
        authors = [a for a in authors if a]
        papers.append(
            Paper(
                paper_id=f"arxiv:{arxiv_id}",
                title=title,
                authors=authors,
                year=_parse_year(published),
                abstract=summary or None,
                url=f"https://arxiv.org/abs/{arxiv_id}",
                pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                source="arxiv",
            )
        )
    return papers


async def search_papers(query: str, limit: int = 10) -> list[Paper]:
    search_query = _build_search_query(query)
    url = (
        f"{ARXIV_API}?search_query={quote_plus(search_query)}"
        f"&start=0&max_results={limit}&sortBy=relevance&sortOrder=descending"
    )
    timeout = httpx.Timeout(45.0, connect=15.0)
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.get(
                    url,
                    headers={
                        "User-Agent": "literature-rag-agent/0.1 (mailto:dev@localhost)",
                        "Accept": "application/atom+xml,application/xml,text/xml,*/*",
                    },
                )
                # 429: stop quickly so unified search can fall back to S2
                if resp.status_code == 429:
                    last_exc = httpx.HTTPStatusError(
                        "arXiv HTTP 429",
                        request=resp.request,
                        response=resp,
                    )
                    logger.warning("arXiv rate limited (429); abort for fallback")
                    break
                resp.raise_for_status()
                return _parse_feed(resp.text)
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            last_exc = exc
            wait = 1.5 * (attempt + 1)
            logger.warning(
                "arXiv search failed (attempt %s): %s; retry in %.1fs",
                attempt + 1,
                exc,
                wait,
            )
            await asyncio.sleep(wait)
    assert last_exc is not None
    raise last_exc
