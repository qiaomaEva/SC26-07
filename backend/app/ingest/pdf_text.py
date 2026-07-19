"""Shared PDF text extraction helpers."""

from __future__ import annotations

import re
from pathlib import Path

from app.ingest.textutil import sanitize_text


def extract_pdf_text(path: Path, max_chars: int | None = None) -> str:
    from pypdf import PdfReader

    from app.core.config import get_settings

    limit = max_chars if max_chars is not None else get_settings().pdf_max_chars
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    text = re.sub(r"\s+", " ", "\n".join(parts)).strip()
    # pypdf sometimes yields lone surrogates that break utf-8 / json
    return sanitize_text(text[:limit])
