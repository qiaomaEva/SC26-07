import asyncio
from types import SimpleNamespace

import httpx

from app.db.models import Paper
from app.ingest import search


def test_online_search_does_not_download_local_rerank_model(monkeypatch):
    papers = [
        Paper(paper_id="p1", title="Text-to-SQL One"),
        Paper(paper_id="p2", title="Text-to-SQL Two"),
    ]
    settings = SimpleNamespace(
        search_candidate_pool=24,
        search_rerank=True,
        embedding_provider="local",
    )

    async def fake_fetch(_query, _limit, on_progress=None):
        return papers

    def unexpected_rerank(*_args, **_kwargs):
        raise AssertionError("cold local reranker should not run")

    events = []
    monkeypatch.setattr(search, "get_settings", lambda: settings)
    monkeypatch.setattr(search, "_fetch_candidates", fake_fetch)
    monkeypatch.setattr(search, "local_embedding_model_cached", lambda: False)
    monkeypatch.setattr(search, "rerank_papers", unexpected_rerank)

    result = asyncio.run(
        search.search_papers(
            "Text-to-SQL",
            limit=2,
            on_progress=lambda message, step: events.append((step, message)),
        )
    )

    assert result == papers
    assert events == [
        (
            "rerank",
            "正在返回检索结果…\n候选：2 篇 · 使用论文源相关性排序",
        )
    ]


def test_s2_without_api_key_falls_back_on_first_rate_limit(monkeypatch):
    calls = 0

    async def rate_limited(_query, limit):
        nonlocal calls
        calls += 1
        request = httpx.Request("GET", "https://api.example.test/search")
        response = httpx.Response(429, request=request)
        raise httpx.HTTPStatusError(
            "rate limited",
            request=request,
            response=response,
        )

    async def unexpected_sleep(_seconds):
        raise AssertionError("rate limit without an API key should not retry")

    monkeypatch.setattr(
        search,
        "get_settings",
        lambda: SimpleNamespace(semantic_scholar_api_key=""),
    )
    monkeypatch.setattr(search.s2_client, "search_papers", rate_limited)
    monkeypatch.setattr(search.asyncio, "sleep", unexpected_sleep)

    try:
        asyncio.run(search._search_s2_with_retry("Text-to-SQL", limit=8))
    except httpx.HTTPStatusError:
        pass
    else:
        raise AssertionError("expected the initial 429 to be propagated")

    assert calls == 1
