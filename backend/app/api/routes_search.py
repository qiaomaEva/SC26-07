from fastapi import APIRouter, HTTPException

from app.db.models import SearchRequest, SearchResponse
from app.ingest.search import search_papers

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    try:
        papers = await search_papers(query, limit=req.limit)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Paper search failed: {exc}. "
                "Tips: set SEMANTIC_SCHOLAR_API_KEY, or set PAPER_SEARCH_SOURCE=arxiv in .env"
            ),
        ) from exc
    return SearchResponse(papers=papers)
