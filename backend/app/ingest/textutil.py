"""Sanitize text that may contain lone UTF-16 surrogates (common from PDF extract)."""

from __future__ import annotations
import unicodedata


def sanitize_text(value: str | None) -> str:
    if not value:
        return ""
    # Lone surrogates cannot be UTF-8 encoded; drop them before json/db/logging
    text = value.encode("utf-8", errors="ignore").decode("utf-8")
    # Compatibility forms (ligatures etc.); math italics mostly stay but still helps
    return unicodedata.normalize("NFKC", text)
