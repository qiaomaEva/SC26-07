import pytest

from app.db.models import Paper
from app.index import pipeline


def test_index_paper_restores_vectors_when_sqlite_commit_fails(monkeypatch):
    events = []
    snapshot = {"ids": ["old"]}

    monkeypatch.setattr(pipeline, "chunk_text", lambda _text: ["new chunk"])
    monkeypatch.setattr(
        pipeline,
        "embed_documents",
        lambda docs: events.append(("embed", docs)) or [[0.1, 0.2]],
    )
    monkeypatch.setattr(
        pipeline,
        "replace_paper_vectors",
        lambda *_args: events.append(("replace", None)) or snapshot,
    )

    def fail_commit(_paper, _chunks):
        events.append(("sqlite", None))
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(pipeline.db, "upsert_paper_and_replace_chunks", fail_commit)
    monkeypatch.setattr(
        pipeline,
        "restore_paper_vectors",
        lambda paper_id, old: events.append(("restore", (paper_id, old))),
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        pipeline.index_paper(Paper(paper_id="p1", title="Paper"))

    assert [event[0] for event in events] == ["embed", "replace", "sqlite", "restore"]
    assert events[-1][1] == ("p1", snapshot)


def test_index_paper_invalidates_bm25_after_commit(monkeypatch):
    events = []
    monkeypatch.setattr(pipeline, "chunk_text", lambda _text: ["new chunk"])
    monkeypatch.setattr(pipeline, "embed_documents", lambda _docs: [[0.1]])
    monkeypatch.setattr(pipeline, "replace_paper_vectors", lambda *_args: {})
    monkeypatch.setattr(
        pipeline.db,
        "upsert_paper_and_replace_chunks",
        lambda _paper, _chunks: events.append("commit"),
    )
    monkeypatch.setattr(
        pipeline, "invalidate_bm25_index", lambda: events.append("invalidate")
    )
    monkeypatch.setattr(pipeline, "rebuild_bm25_index", lambda: events.append("rebuild"))

    pipeline.index_paper(Paper(paper_id="p1", title="Paper"))

    assert events == ["commit", "invalidate", "rebuild"]
