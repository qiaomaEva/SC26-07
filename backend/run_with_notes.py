import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.api.routes_search import router as search_router
from app.api.routes_library import router as library_router
from app.api.routes_chat import router as chat_router
from app.db.models import Note, CreateNoteRequest, UpdateNoteRequest
from app.db import sqlite as db
from app.index.embedder import embedding_status
from app.db.sqlite import init_db, rebuild_bm25_index

settings = get_settings()
app = FastAPI(title="Literature RAG Agent", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(search_router)
app.include_router(library_router)
app.include_router(chat_router)


@app.get("/notes", response_model=list[Note])
def list_notes():
    return db.list_notes()

@app.patch("/notes/{note_id}", response_model=Note)
@app.post("/notes", response_model=Note)
def create_note(req: CreateNoteRequest):
    return db.create_note(title=req.title, content=req.content)

def update_note(note_id: str, req: UpdateNoteRequest):
    note = db.update_note(note_id, title=req.title, content=req.content, pinned=req.pinned)
    if not note:
        raise HTTPException(status_code=404, detail="note not found")
    return note

@app.delete("/notes/{note_id}")
def delete_note(note_id: str):
    db.delete_note(note_id)
    return {"ok": True}

# POST route via add_api_route
def _create_note(req: CreateNoteRequest):
    return db.create_note(title=req.title, content=req.content)
    init_db()
    rebuild_bm25_index()

"/notes", _create_note, methods=["POST"], response_model=Note)

init_db()
rebuild_bm25_index()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/embedding/status")
def get_embedding_status():
    return embedding_status()
