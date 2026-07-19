from types import SimpleNamespace

from app.index import bm25_store, chunking


def test_tokenize_normalizes_punctuation_and_cjk():
    tokens = bm25_store._tokenize("Cardinality, estimation! 中文检索")

    assert "cardinality" in tokens
    assert "estimation" in tokens
    assert "中文" in tokens
    assert "检索" in tokens


def test_cjk_local_chunks_stay_below_minilm_token_budget(monkeypatch):
    monkeypatch.setattr(
        chunking,
        "get_settings",
        lambda: SimpleNamespace(
            chunk_size=900,
            chunk_overlap=150,
            embedding_provider="local",
        ),
    )

    chunks = chunking.chunk_text("中文内容。" * 200)

    assert len(chunks) > 1
    assert max(map(len, chunks)) <= 220


def test_sparse_scope_is_filtered_before_top_k(monkeypatch):
    class FakeBm25:
        def get_scores(self, _tokens):
            return [100.0, 1.0]

    monkeypatch.setitem(bm25_store._cache, "bm25", FakeBm25())
    monkeypatch.setitem(
        bm25_store._cache,
        "docs",
        [
            {
                "chunk_id": "outside",
                "paper_id": "outside",
                "title": "Outside",
                "year": 2024,
                "text": "outside",
            },
            {
                "chunk_id": "inside",
                "paper_id": "inside",
                "title": "Inside",
                "year": 2023,
                "text": "inside",
            },
        ],
    )

    result = bm25_store.sparse_search(
        "query",
        top_k=1,
        allowed_paper_ids={"inside"},
    )

    assert [hit["chunk_id"] for hit in result] == ["inside"]
