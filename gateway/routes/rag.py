# =========================================================================
# gateway/routes/rag.py
# Semantic RAG Search & Question-Answering Routes
# =========================================================================
from typing import Optional

from fastapi import APIRouter, HTTPException, status

from core.embedder import embed_query
from core.llm import call_llm
from gateway.schemas import RagQueryRequest, RagQueryResultChunk, RagQueryResponse
from storage.postgres_db import PostgresBidDatabase
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/bids", tags=["AI & RAG Search"])
log = get_logger("gateway_rag")
db = PostgresBidDatabase()


@router.post("/ask", response_model=RagQueryResponse, summary="Semantic RAG Search & Q&A")
async def ask_rag(request: RagQueryRequest):
    """
    Sub-5ms Cosine Similarity search over PostgreSQL 16 `gem_bid_chunks` with pgvector HNSW index.
    - Encodes user query using local 768-dim BGE embeddings.
    - Retrieves top-K closest domain chunks (item specifications, ATC terms, compliance clauses).
    - Optionally synthesizes a grounded answer via LLM.
    """
    try:
        # 1. Vectorize the incoming question
        query_vector = embed_query(request.query)

        # 2. Query pgvector HNSW index
        chunks = db.search_chunks(
            query_embedding=query_vector,
            top_k=request.top_k,
            bid_id=request.bid_id,
        )

        # 3. Optional LLM Synthesis
        answer: Optional[str] = None
        if request.synthesize_answer and chunks:
            try:
                # Map chunk fields for LLM prompt builder
                llm_chunks = []
                for c in chunks:
                    meta = c.get("metadata") or {}
                    llm_chunks.append({
                        "bid_no": c.get("bid_id", ""),
                        "chunk": c.get("chunk_text", ""),
                        "chunk_text": c.get("chunk_text", ""),
                        "full_item_name": meta.get("item_name") or meta.get("title", ""),
                        "department": meta.get("department", ""),
                        "product_type": meta.get("product_type", ""),
                        "end_date": meta.get("end_date", ""),
                        "estimated_value": meta.get("estimated_value", ""),
                        "document_url": meta.get("document_url", ""),
                        "score": max(0.0, 1.0 - float(c.get("distance", 1.0))),
                    })
                answer = call_llm(request.query, llm_chunks)
            except Exception as llm_err:
                log.warning(f"LLM synthesis failed: {llm_err}")
                answer = f"Error synthesizing answer: {str(llm_err)}"

        results = [
            RagQueryResultChunk(
                id=c["id"],
                bid_id=c["bid_id"],
                chunk_type=c["chunk_type"],
                chunk_text=c["chunk_text"],
                metadata=c["metadata"] or {},
                distance=round(float(c["distance"]), 4),
            )
            for c in chunks
        ]

        return RagQueryResponse(
            query=request.query,
            answer=answer,
            count=len(results),
            results=results,
        )

    except Exception as e:
        log.error(f"RAG query execution error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Semantic search failed: {str(e)}",
        )
