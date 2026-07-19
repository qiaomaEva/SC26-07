import asyncio
from tempfile import SpooledTemporaryFile

import pytest
from fastapi import HTTPException, UploadFile

from app.api.routes_library import _read_upload_limited
from app.ingest import pdf_import


def test_read_upload_limited_rejects_oversized_file():
    file = SpooledTemporaryFile()
    file.write(b"%PDF-" + b"x" * 20)
    file.seek(0)
    upload = UploadFile(filename="large.pdf", file=file)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_read_upload_limited(upload, max_bytes=10))

    assert exc_info.value.status_code == 413


def test_failed_pdf_parse_removes_staged_upload(monkeypatch, tmp_path):
    monkeypatch.setattr(pdf_import, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        pdf_import,
        "extract_pdf_text",
        lambda _path: (_ for _ in ()).throw(RuntimeError("bad pdf")),
    )

    with pytest.raises(RuntimeError, match="bad pdf"):
        pdf_import.import_pdf_file("broken.pdf", b"%PDF-broken")

    assert list(tmp_path.iterdir()) == []
