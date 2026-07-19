import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import get_settings
from app.db.models import ChatMessage, ChatSession, Folder, Paper


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    settings = get_settings()
    conn = sqlite3.connect(settings.sqlite_abs_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, typedef: str) -> None:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {typedef}")


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS folders (
                folder_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS papers (
                paper_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                authors TEXT NOT NULL DEFAULT '[]',
                year INTEGER,
                abstract TEXT,
                url TEXT,
                pdf_url TEXT,
                source TEXT NOT NULL DEFAULT 'semanticscholar',
                folder_id TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "papers", "folder_id", "TEXT")
        _ensure_column(conn, "papers", "pdf_url", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                paper_id TEXT NOT NULL,
                text TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                token_est INTEGER,
                FOREIGN KEY (paper_id) REFERENCES papers(paper_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                meta TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
            )
            """
        )
        conn.commit()


def _row_to_paper(row: sqlite3.Row) -> Paper:
    keys = row.keys()
    return Paper(
        paper_id=row["paper_id"],
        title=row["title"],
        authors=json.loads(row["authors"] or "[]"),
        year=row["year"],
        abstract=row["abstract"],
        url=row["url"],
        pdf_url=row["pdf_url"] if "pdf_url" in keys else None,
        source=row["source"],
        folder_id=row["folder_id"] if "folder_id" in keys else None,
        created_at=row["created_at"],
    )


def create_folder(name: str) -> Folder:
    folder_id = str(uuid.uuid4())
    created = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO folders (folder_id, name, created_at) VALUES (?, ?, ?)",
            (folder_id, name.strip(), created),
        )
        conn.commit()
    return Folder(folder_id=folder_id, name=name.strip(), created_at=created, paper_count=0)


def list_folders() -> list[Folder]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT f.folder_id, f.name, f.created_at,
                   COUNT(p.paper_id) AS paper_count
            FROM folders f
            LEFT JOIN papers p ON p.folder_id = f.folder_id
            GROUP BY f.folder_id
            ORDER BY f.created_at DESC
            """
        ).fetchall()
    return [
        Folder(
            folder_id=r["folder_id"],
            name=r["name"],
            created_at=r["created_at"],
            paper_count=int(r["paper_count"] or 0),
        )
        for r in rows
    ]


def delete_folder(folder_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE papers SET folder_id = NULL WHERE folder_id = ?",
            (folder_id,),
        )
        conn.execute("DELETE FROM folders WHERE folder_id = ?", (folder_id,))
        conn.commit()


def _upsert_paper_conn(conn: sqlite3.Connection, paper: Paper) -> None:
    created_at = paper.created_at or _now()
    conn.execute(
        """
        INSERT INTO papers (
            paper_id, title, authors, year, abstract, url, pdf_url, source, folder_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(paper_id) DO UPDATE SET
            title=excluded.title,
            authors=excluded.authors,
            year=excluded.year,
            abstract=excluded.abstract,
            url=excluded.url,
            pdf_url=COALESCE(excluded.pdf_url, papers.pdf_url),
            source=excluded.source,
            folder_id=COALESCE(excluded.folder_id, papers.folder_id)
        """,
        (
            paper.paper_id,
            _sanitize(paper.title),
            json.dumps(
                [_sanitize(a) for a in (paper.authors or [])],
                ensure_ascii=False,
            ),
            paper.year,
            _sanitize(paper.abstract) if paper.abstract else paper.abstract,
            paper.url,
            paper.pdf_url,
            paper.source,
            paper.folder_id,
            created_at,
        ),
    )


def upsert_paper(paper: Paper) -> None:
    with _connect() as conn:
        _upsert_paper_conn(conn, paper)
        conn.commit()


def _sanitize(value: str | None) -> str:
    from app.ingest.textutil import sanitize_text

    return sanitize_text(value)


def set_paper_folder(paper_id: str, folder_id: Optional[str]) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE papers SET folder_id = ? WHERE paper_id = ?",
            (folder_id, paper_id),
        )
        conn.commit()


def list_papers(folder_id: Optional[str] = None) -> list[Paper]:
    with _connect() as conn:
        if folder_id == "__none__":
            rows = conn.execute(
                "SELECT * FROM papers WHERE folder_id IS NULL ORDER BY created_at DESC"
            ).fetchall()
        elif folder_id:
            rows = conn.execute(
                "SELECT * FROM papers WHERE folder_id = ? ORDER BY created_at DESC",
                (folder_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM papers ORDER BY created_at DESC"
            ).fetchall()
    return [_row_to_paper(r) for r in rows]


def get_paper(paper_id: str) -> Optional[Paper]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM papers WHERE paper_id = ?", (paper_id,)
        ).fetchone()
    return _row_to_paper(row) if row else None


def paper_ids_in_folders(folder_ids: list[str]) -> list[str]:
    if not folder_ids:
        return []
    placeholders = ",".join("?" for _ in folder_ids)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT paper_id FROM papers WHERE folder_id IN ({placeholders})",
            folder_ids,
        ).fetchall()
    return [r["paper_id"] for r in rows]


def resolve_scope(paper_ids: list[str], folder_ids: list[str]) -> Optional[set[str]]:
    """None = entire library."""
    if not paper_ids and not folder_ids:
        return None
    ids = set(paper_ids or [])
    ids.update(paper_ids_in_folders(folder_ids or []))
    return ids


def _replace_chunks_conn(
    conn: sqlite3.Connection,
    paper_id: str,
    chunks: list[tuple[str, str, int, int]],
) -> None:
    conn.execute("DELETE FROM chunks WHERE paper_id = ?", (paper_id,))
    conn.executemany(
        """
        INSERT INTO chunks (chunk_id, paper_id, text, chunk_index, token_est)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (chunk_id, paper_id, text, idx, token_est)
            for chunk_id, text, idx, token_est in chunks
        ],
    )


def replace_chunks(paper_id: str, chunks: list[tuple[str, str, int, int]]) -> None:
    with _connect() as conn:
        _replace_chunks_conn(conn, paper_id, chunks)
        conn.commit()


def upsert_paper_and_replace_chunks(
    paper: Paper,
    chunks: list[tuple[str, str, int, int]],
) -> None:
    """Commit paper metadata and its current chunks in one SQLite transaction."""
    with _connect() as conn:
        _upsert_paper_conn(conn, paper)
        _replace_chunks_conn(conn, paper.paper_id, chunks)
        conn.commit()


def list_all_chunks() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT c.chunk_id, c.paper_id, c.text, c.chunk_index,
                   p.title, p.year
            FROM chunks c
            JOIN papers p ON p.paper_id = c.paper_id
            ORDER BY c.paper_id, c.chunk_index
            """
        ).fetchall()
    return [dict(r) for r in rows]


def list_chunks_for_papers(paper_ids: set[str] | list[str], limit: int = 40) -> list[dict]:
    """按论文轮询取片段，避免 LIMIT 被同一篇论文占满。"""
    ids = list(dict.fromkeys(paper_ids))
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    per_paper_limit = max(1, math.ceil(limit / len(ids)))
    with _connect() as conn:
        rows = conn.execute(
            f"""
            WITH ranked AS (
                SELECT c.chunk_id, c.paper_id, c.text, c.chunk_index,
                       p.title, p.year,
                       ROW_NUMBER() OVER (
                           PARTITION BY c.paper_id ORDER BY c.chunk_index
                       ) AS paper_rank
                FROM chunks c
                JOIN papers p ON p.paper_id = c.paper_id
                WHERE c.paper_id IN ({placeholders})
            )
            SELECT chunk_id, paper_id, text, chunk_index, title, year
            FROM ranked
            WHERE paper_rank <= ?
            ORDER BY paper_id, chunk_index
            """,
            [*ids, per_paper_limit],
        ).fetchall()
    by_paper: dict[str, list[dict]] = {pid: [] for pid in ids}
    for r in rows:
        pid = r["paper_id"]
        if pid in by_paper:
            by_paper[pid].append(dict(r))
    out: list[dict] = []
    idx = 0
    while len(out) < limit:
        progressed = False
        for pid in ids:
            bucket = by_paper.get(pid) or []
            if idx < len(bucket):
                out.append(bucket[idx])
                progressed = True
                if len(out) >= limit:
                    break
        if not progressed:
            break
        idx += 1
    return out


def list_chunks_for_paper(paper_id: str) -> list[dict]:
    """All chunks for one paper, ordered by chunk_index."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT chunk_id, paper_id, text, chunk_index, token_est
            FROM chunks
            WHERE paper_id = ?
            ORDER BY chunk_index ASC
            """,
            (paper_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_session(title: str = "新对话") -> ChatSession:
    session_id = str(uuid.uuid4())
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO chat_sessions (session_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, title, now, now),
        )
        conn.commit()
    return ChatSession(
        session_id=session_id, title=title, created_at=now, updated_at=now
    )


def list_sessions() -> list[ChatSession]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_sessions ORDER BY updated_at DESC"
        ).fetchall()
    return [
        ChatSession(
            session_id=r["session_id"],
            title=r["title"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


def get_session(session_id: str) -> Optional[ChatSession]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    if not row:
        return None
    return ChatSession(
        session_id=row["session_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def touch_session(session_id: str, title: Optional[str] = None) -> None:
    with _connect() as conn:
        if title:
            conn.execute(
                "UPDATE chat_sessions SET updated_at = ?, title = ? WHERE session_id = ?",
                (_now(), title, session_id),
            )
        else:
            conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE session_id = ?",
                (_now(), session_id),
            )
        conn.commit()


def rename_session(session_id: str, title: str) -> Optional[ChatSession]:
    cleaned = " ".join((title or "").split()).strip()
    if not cleaned:
        return get_session(session_id)
    cleaned = cleaned[:40]
    with _connect() as conn:
        conn.execute(
            "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE session_id = ?",
            (cleaned, _now(), session_id),
        )
        conn.commit()
    return get_session(session_id)


def add_message(
    session_id: str,
    role: str,
    content: str,
    meta: Optional[dict[str, Any]] = None,
) -> ChatMessage:
    message_id = str(uuid.uuid4())
    created = _now()
    meta = meta or {}
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO chat_messages
            (message_id, session_id, role, content, meta, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                session_id,
                role,
                content,
                json.dumps(meta, ensure_ascii=False),
                created,
            ),
        )
        conn.commit()
    touch_session(session_id)
    return ChatMessage(
        message_id=message_id,
        session_id=session_id,
        role=role,  # type: ignore[arg-type]
        content=content,
        meta=meta,
        created_at=created,
    )


def list_messages(session_id: str) -> list[ChatMessage]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM chat_messages
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        ).fetchall()
    return [
        ChatMessage(
            message_id=r["message_id"],
            session_id=r["session_id"],
            role=r["role"],
            content=r["content"],
            meta=json.loads(r["meta"] or "{}"),
            created_at=r["created_at"],
        )
        for r in rows
    ]


def delete_session(session_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
        conn.commit()


def create_note(title: str = "Untitled", content: str = ""):
    from app.db.models import Note
    import uuid
    note_id = "note:" + uuid.uuid4().hex[:12]
    with _connect() as conn:
        conn.execute(
            "INSERT INTO notes (note_id, title, content) VALUES (?, ?, ?)",
            (note_id, title, content),
        )
    return Note(note_id=note_id, title=title, content=content)


def list_notes():
    from app.db.models import Note
    with _connect() as conn:
        rows = conn.execute(
            "SELECT note_id, title, content, pinned, created_at, updated_at FROM notes ORDER BY updated_at DESC"
        ).fetchall()
    return [Note(note_id=r[0], title=r[1], content=r[2], pinned=bool(r[3]), created_at=r[4], updated_at=r[5]) for r in rows]


def get_note(note_id: str):
    from app.db.models import Note
    with _connect() as conn:
        row = conn.execute(
            "SELECT note_id, title, content, pinned, created_at, updated_at FROM notes WHERE note_id = ?", (note_id,)
        ).fetchone()
    if not row:
        return None
    return Note(note_id=row[0], title=row[1], content=row[2], pinned=bool(row[3]), created_at=row[4], updated_at=row[5])


def update_note(note_id: str, title=None, content=None, pinned=None):
    from app.db.models import Note
    fields = []
    values = []
    if title is not None:
        fields.append("title = ?")
        values.append(title)
    if content is not None:
        fields.append("content = ?")
        values.append(content)
    if pinned is not None:
        fields.append("pinned = ?")
        values.append(1 if pinned else 0)
    if not fields:
        return get_note(note_id)
    fields.append("updated_at = datetime('now')")
    values.append(note_id)
    with _connect() as conn:
        conn.execute(f"UPDATE notes SET {', '.join(fields)} WHERE note_id = ?", values)
    return get_note(note_id)


def delete_note(note_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM notes WHERE note_id = ?", (note_id,))

