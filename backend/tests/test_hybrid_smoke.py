from app.db import sqlite as db
from app.index import bm25_store, vector_store
from app.index.hybrid import diversify_by_paper, hybrid_search, rrf_fuse


def test_rrf_fuse_merges_and_ranks():
    dense = [
        {"chunk_id": "a", "paper_id": "1", "title": "A", "year": 2020, "text": "ta", "score": 0.9},
        {"chunk_id": "b", "paper_id": "2", "title": "B", "year": 2021, "text": "tb", "score": 0.8},
    ]
    sparse = [
        {"chunk_id": "b", "paper_id": "2", "title": "B", "year": 2021, "text": "tb", "score": 3.0},
        {"chunk_id": "c", "paper_id": "3", "title": "C", "year": 2022, "text": "tc", "score": 2.0},
    ]
    fused = rrf_fuse(dense, sparse, top_k=3)
    ids = [x["chunk_id"] for x in fused]
    assert "b" in ids
    assert len(fused) == 3


def test_diversify_by_paper_covers_all():
    hits = [
        {"chunk_id": f"a{i}", "paper_id": "a", "score": 10 - i}
        for i in range(5)
    ] + [
        {"chunk_id": f"b{i}", "paper_id": "b", "score": 9 - i}
        for i in range(5)
    ] + [
        {"chunk_id": f"c{i}", "paper_id": "c", "score": 8 - i}
        for i in range(5)
    ]
    out = diversify_by_paper(hits, 6, {"a", "b", "c"})
    assert len(out) == 6
    assert {h["paper_id"] for h in out} == {"a", "b", "c"}


def test_hybrid_search_pushes_scope_down_and_fills_missing_paper(monkeypatch):
    calls = []

    def dense(_query, top_k, allowed_paper_ids=None):
        calls.append(("dense", allowed_paper_ids, top_k))
        return [
            {
                "chunk_id": "a1",
                "paper_id": "a",
                "title": "A",
                "year": 2024,
                "text": "ranked A",
                "score": 0.9,
            }
        ]

    def sparse(_query, top_k, allowed_paper_ids=None):
        calls.append(("sparse", allowed_paper_ids, top_k))
        return []

    monkeypatch.setattr(vector_store, "dense_search", dense)
    monkeypatch.setattr(bm25_store, "sparse_search", sparse)
    monkeypatch.setattr(
        db,
        "list_chunks_for_papers",
        lambda _ids, limit: [
            {
                "chunk_id": "a1",
                "paper_id": "a",
                "title": "A",
                "year": 2024,
                "text": "fallback A",
            },
            {
                "chunk_id": "b1",
                "paper_id": "b",
                "title": "B",
                "year": 2023,
                "text": "fallback B",
            },
        ],
    )

    result = hybrid_search("query", top_k=2, allowed_paper_ids={"a", "b"})

    assert {hit["paper_id"] for hit in result} == {"a", "b"}
    assert all(call[1] == {"a", "b"} for call in calls)


def test_dense_search_uses_chroma_metadata_filter(monkeypatch):
    captured = {}

    class FakeCollection:
        def count(self):
            return 10

        def query(self, **kwargs):
            captured.update(kwargs)
            return {
                "ids": [["a1"]],
                "documents": [["text"]],
                "metadatas": [[{"paper_id": "a", "title": "A", "year": 2024}]],
                "distances": [[0.1]],
            }

    class FakeEmbeddings:
        def embed_query(self, _query):
            return [0.1]

    monkeypatch.setattr(vector_store, "get_collection", lambda: FakeCollection())
    monkeypatch.setattr(vector_store, "get_embeddings", lambda: FakeEmbeddings())

    result = vector_store.dense_search("query", allowed_paper_ids={"b", "a"})

    assert result[0]["paper_id"] == "a"
    assert captured["where"] == {"paper_id": {"$in": ["a", "b"]}}
