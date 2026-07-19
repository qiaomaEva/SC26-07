"""Download open-access PDFs (primarily arXiv) and extract text for full-paper RAG."""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import BACKEND_ROOT, get_settings
from app.db.models import Paper
from app.ingest.pdf_text import extract_pdf_text

logger = logging.getLogger(__name__)

PDF_DIR = BACKEND_ROOT / "data" / "pdfs"
MAX_PDF_BYTES = 80 * 1024 * 1024
MAX_REDIRECTS = 5
TRUSTED_PDF_HOSTS = (
    "arxiv.org",
    "export.arxiv.org",
    "cn.arxiv.org",
)

# Limit concurrent arXiv downloads during batch import
_ARXIV_SEM = threading.Semaphore(2)


def _normalize_arxiv_id(raw: str) -> str:
    aid = re.sub(r"\.pdf$", "", raw.strip(), flags=re.I)
    return re.sub(r"v\d+$", "", aid)


def extract_arxiv_id(paper: Paper) -> str | None:
    if paper.paper_id.startswith("arxiv:"):
        raw = paper.paper_id.split(":", 1)[1].strip()
        return _normalize_arxiv_id(raw) if raw else None
    for field in (paper.pdf_url, paper.url):
        if not field:
            continue
        m = re.search(r"arxiv\.org/(?:abs|pdf|html)/([^/\s?#]+)", field, flags=re.I)
        if m:
            return _normalize_arxiv_id(m.group(1))
    return None


def _is_arxiv_host(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return "arxiv.org" in host


def candidate_pdf_urls(paper: Paper) -> list[str]:
    """Prefer export.arxiv.org, then www / cn mirrors. Keep trying PDF URLs."""
    urls: list[str] = []
    aid = extract_arxiv_id(paper)
    if aid:
        urls.extend(
            [
                f"https://export.arxiv.org/pdf/{aid}",
                f"https://export.arxiv.org/pdf/{aid}.pdf",
                f"https://arxiv.org/pdf/{aid}",
                f"https://arxiv.org/pdf/{aid}.pdf",
                f"https://cn.arxiv.org/pdf/{aid}",
                f"https://cn.arxiv.org/pdf/{aid}.pdf",
            ]
        )
    if paper.pdf_url:
        urls.append(paper.pdf_url.strip())
    if paper.url and paper.url.lower().rstrip("/").endswith(".pdf"):
        urls.append(paper.url.strip())

    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        key = u.rstrip("/").lower()
        if u and key not in seen:
            seen.add(key)
            out.append(u)
    return out


def pdf_cache_path(paper: Paper) -> Path:
    safe = re.sub(r"[^\w.\-]+", "_", paper.paper_id)[:120]
    return PDF_DIR / f"{safe}.pdf"


def _validate_public_pdf_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("PDF URL must be a public HTTPS URL")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("PDF URL must not target localhost")

    if any(hostname == trusted or hostname.endswith(f".{trusted}") for trusted in TRUSTED_PDF_HOSTS):
        return
    if hostname.endswith(".arxiv.org"):
        return

    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve PDF host: {hostname}") from exc

    if not addresses or any(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        for address in addresses
    ):
        raise ValueError("PDF URL must resolve only to public IP addresses")


def _download_pdf(client: httpx.Client, initial_url: str) -> bytes:
    url = initial_url
    for _ in range(MAX_REDIRECTS + 1):
        _validate_public_pdf_url(url)
        with client.stream("GET", url, follow_redirects=False) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise httpx.HTTPStatusError(
                        "PDF redirect missing Location header",
                        request=response.request,
                        response=response,
                    )
                url = urljoin(url, location)
                continue

            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > MAX_PDF_BYTES:
                raise ValueError("PDF is larger than the 80 MB download limit")

            data = bytearray()
            for chunk in response.iter_bytes(chunk_size=64 * 1024):
                data.extend(chunk)
                if len(data) > MAX_PDF_BYTES:
                    raise ValueError("PDF is larger than the 80 MB download limit")

            content_type = (response.headers.get("content-type") or "").lower()
            payload = bytes(data)
            if "pdf" not in content_type and not payload.startswith(b"%PDF"):
                raise ValueError(f"response is not a PDF ({content_type})")
            if len(payload) < 1000:
                raise ValueError("PDF download is unexpectedly small")
            return payload

    raise ValueError(f"PDF redirected more than {MAX_REDIRECTS} times")


def _try_download_url(url: str, timeout: httpx.Timeout, retries: int) -> bytes:
    headers = {
        "User-Agent": (
            "literature-rag-agent/0.2 (+https://github.com/local; research; mailto:dev@localhost)"
        ),
        "Accept": "application/pdf,*/*",
    }
    last_exc: Exception | None = None
    use_sem = _is_arxiv_host(url)
    for attempt in range(retries + 1):
        acquired = False
        try:
            if use_sem:
                # Bounded wait so one stuck download cannot freeze the whole batch forever
                if not _ARXIV_SEM.acquire(timeout=90):
                    raise TimeoutError("arXiv download slot wait timed out")
                acquired = True
            with httpx.Client(timeout=timeout, headers=headers, http2=False) as client:
                return _download_pdf(client, url)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "PDF fetch failed %s (attempt %s/%s): %s",
                url,
                attempt + 1,
                retries + 1,
                exc,
            )
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
        finally:
            if acquired:
                _ARXIV_SEM.release()
    assert last_exc is not None
    raise last_exc


def fetch_pdf_bytes(paper: Paper) -> bytes | None:
    """Download PDF bytes; reuse local cache when present. Tries all mirrors sequentially."""
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    cache = pdf_cache_path(paper)
    if cache.exists() and cache.stat().st_size > 1000:
        return cache.read_bytes()

    urls = candidate_pdf_urls(paper)
    if not urls:
        logger.info("No PDF URL candidates for %s", paper.paper_id)
        return None

    settings = get_settings()
    # Per-URL timeout: fail over to next mirror instead of racing (racing leaked slots)
    read_s = float(settings.pdf_fetch_timeout)
    timeout = httpx.Timeout(read_s, connect=min(10.0, read_s), write=30.0, pool=30.0)
    retries = max(0, int(settings.pdf_fetch_retries))

    for url in urls:
        try:
            data = _try_download_url(url, timeout, retries)
            cache.write_bytes(data)
            logger.info("PDF fetched via %s (%s bytes)", url, len(data))
            return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("PDF fetch failed %s: %s", url, exc)

    logger.warning("All PDF mirrors failed for %s", paper.paper_id)
    return None


def fetch_pdf_text(paper: Paper) -> str | None:
    """Download (or reuse) PDF and extract text. Returns None if unavailable."""
    settings = get_settings()
    if not settings.fetch_pdf_on_import:
        return None

    data = fetch_pdf_bytes(paper)
    if not data:
        return None

    cache = pdf_cache_path(paper)
    if not cache.exists():
        PDF_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)

    try:
        text = extract_pdf_text(cache, max_chars=settings.pdf_max_chars)
    except Exception as exc:  # noqa: BLE001
        logger.warning("PDF extract failed for %s: %s", paper.paper_id, exc)
        return None

    text = (text or "").strip()
    if len(text) < 80:
        logger.info("PDF text too short for %s (%s chars)", paper.paper_id, len(text))
        return None
    logger.info("PDF text ready for %s (%s chars)", paper.paper_id, len(text))
    return text
