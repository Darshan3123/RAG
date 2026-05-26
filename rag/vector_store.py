# =========================================================
# rag/vector_store.py
# ChromaDB wrapper — upsert, search, delete by bid_no
# Persists to disk at CHROMA_DIR automatically
# =========================================================
from __future__ import annotations
import chromadb
from chromadb.config import Settings as ChromaSettings
from config.settings import CHROMA_DIR, CHROMA_COLLECTION, RAG_TOP_K
from rag.embedder import (
    build_bid_document,
    chunk_text,
    embed_texts,
    embed_query,
)
from utils.logger import get_logger

log = get_logger("vector_store")

# Lazy singleton
_client     = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(
            path=CHROMA_DIR,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        _collection = _client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        log.info(
            f"ChromaDB ready — collection '{CHROMA_COLLECTION}' "
            f"({_collection.count()} chunks)"
        )
    return _collection


# =========================================================
# UPSERT ONE BID
# Chunks the bid document, embeds each chunk, stores in
# ChromaDB with metadata. Idempotent — safe to call again
# for the same bid (replaces old chunks).
# =========================================================
def upsert_bid(bid: dict):
    col      = _get_collection()
    bid_no   = bid.get("bid_no") or bid.get("document_url", "unknown")
    doc_text = build_bid_document(bid)
    chunks   = chunk_text(doc_text)

    if not chunks:
        log.warning(f"No chunks for bid {bid_no} — skipping vector store")
        return

    # Delete existing chunks for this bid (for re-index)
    _delete_bid_chunks(col, bid_no)

    ids        = [f"{bid_no}__chunk_{i}" for i in range(len(chunks))]
    embeddings = embed_texts(chunks)

    # Metadata stored alongside each chunk for filtering
    metadatas = [
        {
            "bid_no":        bid_no,
            "bid_type":      bid.get("bid_type", ""),
            "product_type":  bid.get("product_type", ""),
            "department":    bid.get("department", ""),
            "end_date":      bid.get("end_date", ""),
            "estimated_value": bid.get("estimated_value", ""),
            "document_url":  bid.get("document_url", ""),
            "chunk_index":   i,
        }
        for i in range(len(chunks))
    ]

    col.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadatas,
    )
    log.debug(f"Upserted {len(chunks)} chunks for {bid_no}")


# =========================================================
# UPSERT BATCH OF BIDS
# =========================================================
def upsert_bids(bids: list[dict]):
    log.info(f"Upserting {len(bids)} bids into vector store...")
    for i, bid in enumerate(bids, 1):
        try:
            upsert_bid(bid)
            if i % 10 == 0:
                log.info(f"  Indexed {i}/{len(bids)}")
        except Exception as e:
            log.error(
                f"  Vector upsert failed for "
                f"{bid.get('bid_no','?')}: {e}"
            )
    log.info(f"Vector store upsert complete. "
             f"Total chunks: {_get_collection().count()}")


# =========================================================
# SEMANTIC SEARCH
# Returns top-K most relevant chunks with their metadata
# =========================================================
def search(
    query: str,
    top_k: int = RAG_TOP_K,
    filters: dict | None = None,
) -> list[dict]:
    """
    Searches vector store for chunks matching the query.

    filters — optional ChromaDB where-clause dict, e.g.:
        {"bid_type": "Product Bid/RAs"}
        {"product_type": "Service"}
        {"department": {"$contains": "Health"}}

    Returns list of dicts:
        {chunk, bid_no, bid_type, product_type,
         department, end_date, estimated_value,
         document_url, distance}
    """
    col         = _get_collection()
    query_vec   = embed_query(query)

    kwargs = {
        "query_embeddings": [query_vec],
        "n_results":        min(top_k, col.count() or 1),
        "include":          ["documents", "metadatas", "distances"],
    }
    if filters:
        kwargs["where"] = filters

    results = col.query(**kwargs)

    output = []
    docs      = results["documents"][0]
    metas     = results["metadatas"][0]
    distances = results["distances"][0]

    for doc, meta, dist in zip(docs, metas, distances):
        output.append({
            "chunk":           doc,
            "score":           round(1 - dist, 4),   # cosine similarity
            "bid_no":          meta.get("bid_no", ""),
            "bid_type":        meta.get("bid_type", ""),
            "product_type":    meta.get("product_type", ""),
            "department":      meta.get("department", ""),
            "end_date":        meta.get("end_date", ""),
            "estimated_value": meta.get("estimated_value", ""),
            "document_url":    meta.get("document_url", ""),
        })

    return output


# =========================================================
# DELETE ALL CHUNKS FOR A BID
# =========================================================
def _delete_bid_chunks(col, bid_no: str):
    try:
        col.delete(where={"bid_no": bid_no})
    except Exception:
        pass  # collection empty or bid not indexed yet


# =========================================================
# FULL RE-INDEX FROM SQLITE DB
# Call this once to build the vector store from scratch,
# or after schema/embedding model changes.
# =========================================================
def reindex_all(db):
    log.info("Starting full re-index from SQLite...")
    bids = db.get_all()
    upsert_bids(bids)
    log.info("Re-index complete.")


# =========================================================
# STATS
# =========================================================
def stats() -> dict:
    col = _get_collection()
    return {
        "collection":   CHROMA_COLLECTION,
        "total_chunks": col.count(),
        "chroma_dir":   CHROMA_DIR,
    }
