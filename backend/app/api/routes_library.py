import asyncio
import json
import threading
from queue import Empty, Queue
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.db import sqlite as db
from app.db.models import (
    CreateFolderRequest,
    Folder,
    ImportRequest,
    ImportResponse,
    LibraryResponse,
    MovePaperRequest,
    Paper,
    PaperChunk,
    PaperChunksResponse,
)
from app.ingest.importer import enrich_papers_with_pdf, import_papers
from app.ingest.pdf_import import import_pdf_file
from app.ingest.textutil import sanitize_text

router = APIRouter(prefix="/library", tags=["library"])


def _safe_json(obj: Any) -> str:
    """JSON encode without failing on lone UTF-16 surrogates in titles/messages."""

    def _clean(value: Any) -> Any:
        if isinstance(value, str):
            return sanitize_text(value)
        if isinstance(value, dict):
            return {k: _clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_clean(v) for v in value]
        return value

    return json.dumps(_clean(obj), ensure_ascii=False)


@router.get("/papers/{paper_id}/pdf")
def get_paper_pdf(paper_id: str):
    paper = db.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="paper not found")
    from app.ingest.pdf_import import UPLOAD_DIR
    if not UPLOAD_DIR.is_dir():
        raise HTTPException(status_code=404, detail="no uploads directory")
    safe = paper_id.replace(":", "_")
    for f in UPLOAD_DIR.iterdir():
        if f.is_file() and safe in f.name:
            return StreamingResponse(
                iter([f.read_bytes()]),
                media_type="application/pdf",
                headers={
                    "Content-Disposition": 'inline; filename="' + f.name + '"'
                }
            )
    raise HTTPException(status_code=404, detail="PDF file not found")


class EnrichPdfRequest(BaseModel):
    paper_ids: list[str] = Field(default_factory=list)


async def _read_upload_limited(file: UploadFile, max_bytes: int) -> bytes:
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"PDF is larger than the {max_bytes // (1024 * 1024)} MB upload limit",
            )
    return bytes(data)


@router.get("", response_model=LibraryResponse)
def list_library() -> LibraryResponse:
    return LibraryResponse(papers=db.list_papers(), folders=db.list_folders())


@router.post("/import", response_model=ImportResponse)
def import_to_library(req: ImportRequest) -> ImportResponse:
    if not req.papers:
        raise HTTPException(status_code=400, detail="papers is empty")
    try:
        ids = import_papers(req.papers, folder_id=req.folder_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"import failed: {exc}") from exc
    return ImportResponse(imported=len(ids), paper_ids=ids)


@router.post("/import/stream")
async def import_to_library_stream(req: ImportRequest) -> StreamingResponse:
    """SSE: per-paper progress, then done with ImportResponse."""
    if not req.papers:
        raise HTTPException(status_code=400, detail="papers is empty")

    event_q: Queue = Queue()
    total = len(req.papers)

    def on_progress(
        current: int, tot: int, title: str, stage: str, message: str
    ) -> None:
        # fetch/done report completed counts; index/bm25 use current-1 until finished
        if stage in {"done", "fetch", "bm25"}:
            completed = min(current, tot)
        else:
            completed = max(0, current - 1)
        event_q.put(
            {
                "type": "progress",
                "current": current,
                "total": tot,
                "title": title,
                "stage": stage,
                "message": message,
                "completed": completed,
            }
        )

    def worker() -> None:
        try:
            ids = import_papers(
                req.papers, folder_id=req.folder_id, on_progress=on_progress
            )
            event_q.put(
                {
                    "type": "done",
                    "response": {"imported": len(ids), "paper_ids": ids},
                }
            )
        except Exception as exc:
            event_q.put({"type": "error", "message": str(exc)})

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    async def event_gen():
        event_q.put(
            {
                "type": "progress",
                "current": 0,
                "total": total,
                "title": "",
                "stage": "start",
                "message": f"准备导入 {total} 篇论文…",
                "completed": 0,
            }
        )
        try:
            while True:
                try:
                    item = await asyncio.to_thread(event_q.get, True, 0.5)
                except Empty:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {_safe_json(item)}\n\n"
                if item.get("type") in {"done", "error"}:
                    break
        finally:
            thread.join(timeout=0.1)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/enrich-pdfs")
def enrich_pdfs(req: EnrichPdfRequest = EnrichPdfRequest()) -> dict:
    """Download open-access PDFs for library papers and re-index full text."""
    try:
        return enrich_papers_with_pdf(req.paper_ids or None)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"enrich failed: {exc}") from exc


@router.get("/folders", response_model=list[Folder])
def get_folders() -> list[Folder]:
    return db.list_folders()


@router.post("/folders", response_model=Folder)
def create_folder(req: CreateFolderRequest) -> Folder:
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="folder name is required")
    return db.create_folder(name)


@router.delete("/folders/{folder_id}")
def remove_folder(folder_id: str) -> dict:
    db.delete_folder(folder_id)
    return {"ok": True}


@router.patch("/papers/{paper_id}/folder", response_model=Paper)
def move_paper(paper_id: str, req: MovePaperRequest) -> Paper:
    if not db.get_paper(paper_id):
        raise HTTPException(status_code=404, detail="paper not found")
    db.set_paper_folder(paper_id, req.folder_id)
    paper = db.get_paper(paper_id)
    assert paper is not None
    return paper


@router.get("/papers/{paper_id}/chunks", response_model=PaperChunksResponse)
def list_paper_chunks(paper_id: str) -> PaperChunksResponse:
    paper = db.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="paper not found")
    rows = db.list_chunks_for_paper(paper_id)
    chunks = [
        PaperChunk(
            chunk_id=r["chunk_id"],
            paper_id=r["paper_id"],
            chunk_index=int(r["chunk_index"]),
            text=sanitize_text(r.get("text") or ""),
            token_est=int(r.get("token_est") or 0),
        )
        for r in rows
    ]
    return PaperChunksResponse(
        paper_id=paper.paper_id,
        title=sanitize_text(paper.title),
        year=paper.year,
        chunks=chunks,
    )


@router.post("/upload-pdf", response_model=Paper)
async def upload_pdf(
    file: UploadFile = File(...),
    folder_id: Optional[str] = Form(default=None),
    title: Optional[str] = Form(default=None),
) -> Paper:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="only .pdf files are supported")
    from app.core.config import get_settings

    settings = get_settings()
    try:
        content = await _read_upload_limited(file, settings.pdf_upload_max_bytes)
    finally:
        await file.close()
    if not content:
        raise HTTPException(status_code=400, detail="empty file")
    if b"%PDF-" not in content[:1024]:
        raise HTTPException(status_code=400, detail="file content is not a PDF")
    try:
        return await asyncio.to_thread(
            import_pdf_file,
            filename=file.filename,
            content=content,
            folder_id=folder_id or None,
            title=title,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"pdf import failed: {exc}") from exc
