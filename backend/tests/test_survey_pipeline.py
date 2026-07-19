from app.rag.survey_pipeline import (
    _dedupe_hits,
    _parse_json_blob,
    _remap_note_citations,
)


def test_dedupe_hits():
    hits = [
        {"chunk_id": "a1", "paper_id": "p1"},
        {"chunk_id": "a1", "paper_id": "p1"},
        {"chunk_id": "b1", "paper_id": "p2"},
    ]
    out = _dedupe_hits(hits)
    assert len(out) == 2
    assert {h["chunk_id"] for h in out} == {"a1", "b1"}


def test_parse_json_blob():
    text = 'Some intro {"topic": "test", "personas": [{"role": "A", "focus": "B"}]} trailing'
    data = _parse_json_blob(text)
    assert data["topic"] == "test"
    assert len(data["personas"]) == 1


def test_remap_note_citations_to_merged_context():
    local_hits = [{"chunk_id": "b"}, {"chunk_id": "a"}]
    positions = {"a": 1, "b": 3}

    result = _remap_note_citations(
        "first [1], second [2], invalid [9], year [2024]",
        local_hits,
        positions,
    )

    assert result == "first [3], second [1], invalid , year [2024]"
