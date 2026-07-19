import uuid
from fastapi import APIRouter, HTTPException
from app.db import sqlite as db
from app.db.models import CreateNoteRequest, Note, UpdateNoteRequest

router = APIRouter(tags=["notes"])


@router.get("/notes", response_model=list[Note])
def list_notes():
    return db.list_notes()


@router.post("/notes", response_model=Note)
def create_note(req: CreateNoteRequest):
    return db.create_note(title=req.title, content=req.content)


@router.patch("/notes/{note_id}", response_model=Note)
def update_note(note_id: str, req: UpdateNoteRequest):
    note = db.update_note(note_id, title=req.title, content=req.content, pinned=req.pinned)
    if not note:
        raise HTTPException(status_code=404, detail="note not found")
    return note


@router.delete("/notes/{note_id}")
def delete_note(note_id: str):
    db.delete_note(note_id)
    return {"ok": True}
