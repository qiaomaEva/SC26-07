import logging
from typing import Any, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import get_settings
from app.index.embedder import get_embeddings

COLLECTION_NAME = "literature_chunks"
logger = logging.getLogger(__name__)


def get_chroma_client() -> chromadb.PersistentClient:
    settings = get_settings()
    return chromadb.PersistentClient(
        path=str(settings.chroma_abs_path),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def get_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def upsert_vectors(
    ids: list[str],
    documents: list[str],
    metadatas: list[dict[str, Any]],
) -> None:
    if not ids:
        return
    embeddings = get_embeddings().embed_documents(documents)
    collection = get_collection()
    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings,
    )


def embed_documents(documents: list[str]) -> list[list[float]]:
    return get_embeddings().embed_documents(documents)


def snapshot_paper_vectors(paper_id: str) -> dict[str, Any]:
    collection = get_collection()
    result = collection.get(
        where={"paper_id": paper_id},
        include=["documents", "metadatas", "embeddings"],
    )
    return {
        "ids": list(result.get("ids") or []),
        "documents": result.get("documents"),
        "metadatas": result.get("metadatas"),
        "embeddings": result.get("embeddings"),
    }


def restore_paper_vectors(paper_id: str, snapshot: dict[str, Any]) -> None:
    collection = get_collection()
    collection.delete(where={"paper_id": paper_id})
    ids = snapshot.get("ids") or []
    if not ids:
        return
    collection.upsert(
        ids=ids,
        documents=snapshot.get("documents"),
        metadatas=snapshot.get("metadatas"),
        embeddings=snapshot.get("embeddings"),
    )


def replace_paper_vectors(
    paper_id: str,
    ids: list[str],
    documents: list[str],
    metadatas: list[dict[str, Any]],
    embeddings: list[list[float]],
) -> dict[str, Any]:
    """Replace one paper's vectors and restore its previous snapshot on failure."""
    snapshot = snapshot_paper_vectors(paper_id)
    collection = get_collection()
    try:
        collection.delete(where={"paper_id": paper_id})
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
    except Exception:
        try:
            restore_paper_vectors(paper_id, snapshot)
        except Exception:
            logger.exception("Failed to restore vector snapshot for %s", paper_id)
        raise
    return snapshot


def delete_by_paper_id(paper_id: str) -> None:
    collection = get_collection()
    collection.delete(where={"paper_id": paper_id})


def dense_search(
    query: str,
    top_k: int = 10,
    allowed_paper_ids: Optional[set[str] | list[str]] = None,
) -> list[dict[str, Any]]:
    if allowed_paper_ids is not None and not allowed_paper_ids:
        return []
    collection = get_collection()
    if collection.count() == 0:
        return []
    query_embedding = get_embeddings().embed_query(query)
    where = None
    if allowed_paper_ids is not None:
        where = {"paper_id": {"$in": sorted(set(allowed_paper_ids))}}
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    hits: list[dict[str, Any]] = []
    ids = result.get("ids", [[]])[0]
    docs = result.get("documents", [[]])[0]
    metas = result.get("metadatas", [[]])[0]
    dists = result.get("distances", [[]])[0]
    for i, chunk_id in enumerate(ids):
        distance = dists[i] if i < len(dists) else 1.0
        # cosine distance -> similarity-like score
        score = 1.0 - float(distance)
        meta = metas[i] or {}
        hits.append(
            {
                "chunk_id": chunk_id,
                "paper_id": meta.get("paper_id", ""),
                "title": meta.get("title", ""),
                "year": meta.get("year"),
                "text": docs[i] or "",
                "score": score,
            }
        )
    return hits


def _normalize_year(year: Optional[Any]) -> Optional[int]:
    if year is None or year == "":
        return None
    try:
        return int(year)
    except (TypeError, ValueError):
        return None


def sanitize_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Chroma metadata values must be str | int | float | bool."""
    year = _normalize_year(meta.get("year"))
    return {
        "paper_id": str(meta.get("paper_id", "")),
        "title": str(meta.get("title", ""))[:500],
        "year": year if year is not None else -1,
        "chunk_index": int(meta.get("chunk_index", 0)),
    }
