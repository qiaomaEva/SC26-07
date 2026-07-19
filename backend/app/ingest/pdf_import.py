import re
import uuid
from pathlib import Path

from app.core.config import BACKEND_ROOT
from app.db.models import Paper
from app.ingest.pdf_text import extract_pdf_text

UPLOAD_DIR = BACKEND_ROOT / "data" / "uploads"



def _guess_title_from_text(text: str) -> str | None:
    if not text or not text.strip():
        return None
    head = text[:3000].strip()
    # Cut off at common abstract/intro markers (title comes before these)
    for marker in ['ABST', 'abstract', 'abstract.', 'introduction', '1. introduction']:
        idx = head.lower().find(marker)
        if idx > 20:
            head = head[:idx]
            break
    # Strip leading junk: arXiv, DOI, page numbers
    head = __import__('re').sub(r'^(arxiv[:\s]*\d+\.\d+[a-z]?\d*|doi[:\s]*10\.\S+|\d+\s*)', '', head, flags=__import__('re').I).strip()
    # Take first 30 words as the title
    words = head.split()
    title = ' '.join(words[:15]).strip()
    if len(title) >= 10:
        return title[:200]
    return None

def import_pdf_file(
    filename: str,
    content: bytes,
    folder_id: str | None = None,
    title: str | None = None,
) -> Paper:
    from app.ingest.importer import import_papers

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    paper_id = f"pdf:{uuid.uuid4().hex[:12]}"
    safe_name = re.sub(r"[^\w.\-]+", "_", filename)[:80]
    dest = UPLOAD_DIR / f"{paper_id.replace(':', '_')}_{safe_name}"
    try:
        dest.write_bytes(content)
        text = extract_pdf_text(dest)
        guessed = _guess_title_from_text(text) if not title else None
        display_title = (title or guessed or Path(filename).stem or "Untitled PDF").strip()
        abstract = text[:800] if text else None
        paper = Paper(
            paper_id=paper_id,
            title=display_title,
            authors=[],
            year=None,
            abstract=abstract,
            url=None,
            source="pdf",
            folder_id=folder_id,
        )
        import_papers(
            [paper],
            folder_id=folder_id,
            full_texts={paper_id: text or display_title},
        )
        return paper
    except Exception:
        dest.unlink(missing_ok=True)
        raise
