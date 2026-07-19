import asyncio

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from app.api import routes_chat
from app.db.models import ChatRequest, ChatResponse, LLMConfig
from app.rag import chain


def _config() -> LLMConfig:
    return LLMConfig(
        api_key="test-secret-key",
        base_url="https://model.example.test/v1/",
        model="example-model",
        timeout_seconds=12,
    )


def test_llm_config_normalizes_base_url():
    assert _config().base_url == "https://model.example.test/v1"


def test_get_chat_model_prefers_request_config(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(chain, "ChatOpenAI", FakeChatOpenAI)
    chain.get_chat_model(_config())

    assert captured == {
        "api_key": "test-secret-key",
        "base_url": "https://model.example.test/v1",
        "model": "example-model",
        "temperature": 0,
        "timeout": 12,
    }


def test_llm_config_rejects_out_of_range_timeout():
    with pytest.raises(ValidationError):
        LLMConfig(
            api_key="test-secret-key",
            base_url="https://model.example.test/v1",
            model="example-model",
            timeout_seconds=2,
        )


def test_model_connection_endpoint_uses_submitted_config(monkeypatch):
    captured = {}

    class FakeModel:
        async def ainvoke(self, messages):
            captured["messages"] = messages
            return AIMessage(content="OK")

    def fake_get_chat_model(config):
        captured["config"] = config
        return FakeModel()

    monkeypatch.setattr(routes_chat, "get_chat_model", fake_get_chat_model)
    config = _config()
    response = asyncio.run(routes_chat.test_model(config))

    assert captured["config"] is config
    assert response.ok is True
    assert response.model == "example-model"
    assert response.message == "OK"


def test_model_connection_endpoint_reports_timeout(monkeypatch):
    class FakeModel:
        async def ainvoke(self, _messages):
            return AIMessage(content="too late")

    async def fake_wait_for(_awaitable, *, timeout):
        assert timeout == 12
        _awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(routes_chat, "get_chat_model", lambda _config: FakeModel())
    monkeypatch.setattr(routes_chat.asyncio, "wait_for", fake_wait_for)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes_chat.test_model(_config()))

    assert exc_info.value.status_code == 504
    assert exc_info.value.detail == "模型连接超时：超过 12 秒未返回结果"


def test_chat_forwards_request_model_config(monkeypatch):
    captured = {}

    async def fake_handle_chat(**kwargs):
        captured.update(kwargs)
        return ChatResponse(session_id="session", answer="ok")

    monkeypatch.setattr(routes_chat, "handle_chat", fake_handle_chat)
    config = _config()
    response = asyncio.run(
        routes_chat.chat(ChatRequest(question="test", llm_config=config))
    )

    assert response.answer == "ok"
    assert captured["llm_config"] is config


def test_detect_intent_skips_model_for_explicit_english_paper_search():
    class UnexpectedModel:
        async def ainvoke(self, _messages):
            raise AssertionError("explicit English paper search should not call the model")

    result = asyncio.run(
        chain.detect_intent(
            "帮我找 Text-to-SQL 相关论文",
            UnexpectedModel(),
        )
    )

    assert result == ("search", "Text-to-SQL", "Text-to-SQL")


def test_detect_intent_keeps_english_query_for_local_qa():
    class FakeModel:
        async def ainvoke(self, _messages):
            return AIMessage(
                content=(
                    '{"intent":"qa","topic":"基数估计",'
                    '"query_en":"learned cardinality estimation"}'
                )
            )

    result = asyncio.run(
        chain.detect_intent("这些方法如何进行基数估计？", FakeModel())
    )

    assert result == ("qa", "基数估计", "learned cardinality estimation")
