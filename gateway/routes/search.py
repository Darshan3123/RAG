# =========================================================================
# gateway/routes/search.py
# Group 4: Search & AI Semantic Retrieval APIs (Quick, Keyword & pgvector)
# =========================================================================
import time
from typing import Optional
from fastapi import APIRouter, Query

from gateway.schemas import (
    KeywordSearchResponse,
    QuickSearchResponse,
    SemanticSearchRequest,
    SemanticSearchResponse,
    SemanticSearchResultItem,
)
from storage.postgres_db import PostgresBidDatabase
from core.embedder import embed_query
from utils.logger import get_logger

router = APIRouter(prefix="/search", tags=["3. Search & Semantic Retrieval"])
db = PostgresBidDatabase()
log = get_logger("search_api")


@router.get("/quick", response_model=QuickSearchResponse, summary="Instant Auto-Complete Search")
def quick_search(
    q: str = Query(..., min_length=1, description="Search term for auto-complete"),
    limit: int = Query(5, ge=1, le=20, description="Suggestions per category"),
):
    """
    Instant auto-complete suggestions returning matching bid numbers,
    procuring organizations, and item categories.
    """
    return db.quick_search(query=q, limit=limit)


@router.get("/keyword", response_model=KeywordSearchResponse, summary="Fast Fuzzy Keyword Search (pg_trgm)")
def keyword_search(
    q: str = Query(..., min_length=1, description="Keyword or phrase to search"),
    limit: int = Query(10, ge=1, le=50, description="Maximum matches to return"),
):
    """
    High-speed fuzzy trigram and keyword search over item categories,
    departments, and procuring organizations.
    """
    matches = db.keyword_search(query=q, limit=limit)
    return {
        "success": True,
        "query": q,
        "matches": matches,
    }


@router.post("/semantic", response_model=SemanticSearchResponse, summary="Natural Language Semantic Search (pgvector)")
def semantic_search(request: SemanticSearchRequest):
    """
    Takes natural language procurement intent, generates a 768-dimensional BGE
    embedding vector on the fly, and performs sub-5ms cosine similarity search
    against PostgreSQL's `gem_bid_chunks` via HNSW vector index.
    """
    t0 = time.perf_counter()
    query_vec = embed_query(request.query)
    raw_results = db.search_chunks(query_vec, top_k=request.top_k)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

    results = []
    for r in raw_results:
        dist = float(r.get("distance", 0.0))
        sim = round(max(0.0, 1.0 - dist), 4)
        results.append(
            SemanticSearchResultItem(
                bid_no=r.get("bid_id", "").replace("_", "/"),
                chunk_type=r.get("chunk_type", "general_pdf"),
                similarity_score=sim,
                distance=round(dist, 4),
                matching_text=r.get("chunk_text", ""),
                metadata=r.get("metadata"),
            )
        )

    return SemanticSearchResponse(
        success=True,
        query=request.query,
        retrieval_latency_ms=elapsed_ms,
        results_count=len(results),
        results=results,
    )
