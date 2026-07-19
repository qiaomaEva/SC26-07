import asyncio

import pytest

from app.api import routes_chat
from app.db.models import ChatRequest
from app.rag import chain


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


def test_cancel_endpoint_cancels_registered_task():
    async def scenario():
        started = asyncio.Event()

        async def wait_forever():
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(wait_forever())
        routes_chat._active_chat_tasks["cancel-me"] = task
        await started.wait()

        result = await routes_chat.cancel_chat_task("cancel-me")

        assert result == {
            "ok": True,
            "cancelled": True,
            "request_id": "cancel-me",
        }
        with pytest.raises(asyncio.CancelledError):
            await task
        routes_chat._active_chat_tasks.pop("cancel-me", None)

    asyncio.run(scenario())


def test_stream_emits_started_then_cancelled(monkeypatch):
    async def fake_handle_chat(*, on_session, on_progress, **_kwargs):
        on_session("session-1")
        on_progress("正在生成回答…", "generate")
        await asyncio.Event().wait()

    monkeypatch.setattr(routes_chat, "handle_chat", fake_handle_chat)

    async def scenario():
        request_id = "stream-cancel"
        response = await routes_chat.chat_stream(
            ChatRequest(question="test", request_id=request_id),
            ConnectedRequest(),
        )
        iterator = response.body_iterator

        started_event = await iterator.__anext__()
        assert '"type": "started"' in started_event
        assert '"session_id": "session-1"' in started_event

        result = await routes_chat.cancel_chat_task(request_id)
        assert result["cancelled"] is True

        cancelled_event = await iterator.__anext__()
        if '"type": "progress"' in cancelled_event:
            cancelled_event = await iterator.__anext__()
        assert '"type": "cancelled"' in cancelled_event
        assert '"message": "已停止生成"' in cancelled_event

        await iterator.aclose()
        assert request_id not in routes_chat._active_chat_tasks

    asyncio.run(scenario())


def test_cancelling_intent_task_reaches_async_model_call():
    async def scenario():
        started = asyncio.Event()

        class BlockingModel:
            async def ainvoke(self, _messages):
                started.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(
            chain.detect_intent("请解释这些论文的方法", BlockingModel())
        )
        await started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
