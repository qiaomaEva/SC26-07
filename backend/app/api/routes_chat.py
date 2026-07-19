import asyncio
import json
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from app.db import sqlite as db
from app.db.models import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatSession,
    LLMConfig,
    LLMTestResponse,
    RenameSessionRequest,
)
from app.rag.chain import get_chat_model, handle_chat

router = APIRouter(tags=["chat"])
_active_chat_tasks: dict[str, asyncio.Task[None]] = {}


def _safe_model_error(exc: Exception, api_key: str) -> str:
    message = f"{type(exc).__name__}: {exc}".replace(api_key, "***")
    return message[:800]


@router.post("/model/test", response_model=LLMTestResponse)
async def test_model(config: LLMConfig) -> LLMTestResponse:
    try:
        model = get_chat_model(config)
        response = await asyncio.wait_for(
            model.ainvoke([HumanMessage(content="Reply with exactly: OK")]),
            timeout=config.timeout_seconds,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=f"模型连接超时：超过 {config.timeout_seconds:g} 秒未返回结果",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"模型连接失败：{_safe_model_error(exc, config.api_key)}",
        ) from exc

    content = response.content if isinstance(response.content, str) else str(response.content)
    return LLMTestResponse(
        ok=True,
        model=config.model,
        message=content.strip() or "连接成功",
    )


@router.get("/sessions", response_model=list[ChatSession])
def list_sessions() -> list[ChatSession]:
    return db.list_sessions()


@router.post("/sessions", response_model=ChatSession)
def create_session() -> ChatSession:
    return db.create_session("新对话")


@router.patch("/sessions/{session_id}", response_model=ChatSession)
def rename_session(session_id: str, req: RenameSessionRequest) -> ChatSession:
    if not db.get_session(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    updated = db.rename_session(session_id, title)
    assert updated is not None
    return updated


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    db.delete_session(session_id)
    return {"ok": True}


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessage])
def get_messages(session_id: str) -> list[ChatMessage]:
    if not db.get_session(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return db.list_messages(session_id)


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    try:
        return await handle_chat(
            question=question,
            session_id=req.session_id,
            paper_ids=req.paper_ids,
            folder_ids=req.folder_ids,
            top_k=req.top_k,
            llm_config=req.llm_config,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"chat failed: {exc}") from exc


@router.delete("/chat/tasks/{request_id}")
async def cancel_chat_task(request_id: str) -> dict:
    task = _active_chat_tasks.get(request_id)
    if task is None or task.done():
        return {"ok": True, "cancelled": False, "request_id": request_id}
    task.cancel()
    return {"ok": True, "cancelled": True, "request_id": request_id}


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    """SSE stream: progress events, then done/error with final ChatResponse."""
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    request_id = req.request_id or uuid.uuid4().hex
    active = _active_chat_tasks.get(request_id)
    if active is not None and not active.done():
        raise HTTPException(status_code=409, detail="request_id is already active")

    event_q: asyncio.Queue[dict] = asyncio.Queue()
    started_session_id: str | None = None

    def on_progress(message: str, step: str = "") -> None:
        event_q.put_nowait(
            {"type": "progress", "step": step, "message": message}
        )

    def on_session(session_id: str) -> None:
        nonlocal started_session_id
        started_session_id = session_id
        event_q.put_nowait(
            {
                "type": "started",
                "request_id": request_id,
                "session_id": session_id,
            }
        )

    async def worker() -> None:
        try:
            result = await handle_chat(
                question=question,
                session_id=req.session_id,
                paper_ids=req.paper_ids,
                folder_ids=req.folder_ids,
                top_k=req.top_k,
                llm_config=req.llm_config,
                on_progress=on_progress,
                on_session=on_session,
            )
            event_q.put_nowait(
                {
                    "type": "done",
                    "response": json.loads(result.model_dump_json()),
                }
            )
        except asyncio.CancelledError:
            event_q.put_nowait(
                {
                    "type": "cancelled",
                    "request_id": request_id,
                    "session_id": started_session_id,
                    "message": "已停止生成",
                }
            )
            raise
        except Exception as exc:
            event_q.put_nowait({"type": "error", "message": str(exc)})
        finally:
            current = asyncio.current_task()
            if _active_chat_tasks.get(request_id) is current:
                _active_chat_tasks.pop(request_id, None)

    task = asyncio.create_task(worker(), name=f"chat:{request_id}")
    _active_chat_tasks[request_id] = task

    async def event_gen():
        try:
            while True:
                if await request.is_disconnected():
                    task.cancel()
                    break
                try:
                    item = await asyncio.wait_for(event_q.get(), timeout=0.5)
                except TimeoutError:
                    # keepalive so proxies / browsers keep the connection
                    yield ": keepalive\n\n"
                    continue
                payload = json.dumps(item, ensure_ascii=False)
                yield f"data: {payload}\n\n"
                if item.get("type") in {"done", "error", "cancelled"}:
                    break
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if _active_chat_tasks.get(request_id) is task:
                _active_chat_tasks.pop(request_id, None)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )
