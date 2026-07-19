from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_chat import router as chat_router
from app.api.routes_notes import router as notes_router
from app.api.routes_library import router as library_router
from app.api.routes_search import router as search_router
from app.core.config import get_settings
from app.db.sqlite import init_db
from app.index.bm25_store import rebuild_bm25_index
from app.index.embedder import embedding_status


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    rebuild_bm25_index()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Literature RAG Agent",
        description="个人文献检索 + 混合检索 RAG 问答助手",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(search_router)
    app.include_router(library_router)
    app.include_router(notes_router)
    app.include_router(chat_router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/embedding/status")
    def get_embedding_status():
        return embedding_status()

    return app


app = create_app()
app.include_router(notes_router)
