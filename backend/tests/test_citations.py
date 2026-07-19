from app.rag.chain import _qa_response, _validate_answer_citations


def _hits():
    return [
        {
            "chunk_id": "a1",
            "paper_id": "a",
            "title": "Paper A",
            "year": 2024,
            "text": "A evidence",
            "score": 0.9,
        },
        {
            "chunk_id": "b1",
            "paper_id": "b",
            "title": "Paper B",
            "year": 2023,
            "text": "B evidence",
            "score": 0.8,
        },
    ]


def test_validate_answer_citations_removes_out_of_range_markers():
    answer, cited = _validate_answer_citations(
        "Claim [2], repeated [2], bad [9], year [2024].",
        _hits(),
    )

    assert answer == "Claim [2], repeated [2], bad , year [2024]."
    assert [hit["chunk_id"] for hit in cited] == ["b1"]


def test_qa_response_lists_only_papers_cited_in_answer():
    response = _qa_response("Only the second source is used [2].", _hits())

    assert [citation.paper_id for citation in response.citations] == ["b"]
    assert len(response.evidence) == 2
    assert response.evidence[1].chunk_id == "b1"
