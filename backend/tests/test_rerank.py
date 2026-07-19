from app.db.models import Paper
from app.ingest.rerank import _cosine, _lexical_overlap, _paper_doc


def test_cosine_identical():
    v = [1.0, 0.0, 0.0]
    assert abs(_cosine(v, v) - 1.0) < 1e-6


def test_lexical_prefers_abstract_match():
    q = "cardinality estimation"
    title = "A System for Databases"
    abstract = "We study cardinality estimation for query optimizers."
    assert _lexical_overlap(q, title, abstract) > _lexical_overlap(q, title, "")


def test_paper_doc():
    p = Paper(
        paper_id="x",
        title="T",
        authors=[],
        abstract="A",
        source="arxiv",
    )
    assert _paper_doc(p) == ("T", "A")
