# =========================================================
# rag/vector_store.py
# IMPROVED: Hybrid search (semantic + keyword scoring)
# =========================================================
from __future__ import annotations
import re
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
# =========================================================
def upsert_bid(bid: dict):
    col    = _get_collection()
    bid_no = bid.get("bid_no") or bid.get("document_url", "unknown")

    doc_text = build_bid_document(bid)
    chunks   = chunk_text(doc_text)

    if not chunks:
        log.warning(f"No chunks for {bid_no} — skipping")
        return

    _delete_bid_chunks(col, bid_no)

    ids        = [f"{bid_no}__chunk_{i}" for i in range(len(chunks))]
    embeddings = embed_texts(chunks)

    metadatas = [
        {
            "bid_no":          bid_no,
            "bid_type":        bid.get("bid_type", ""),
            "product_type":    bid.get("product_type", ""),
            "full_item_name":  bid.get("full_item_name", ""),
            "quantity":        bid.get("quantity", ""),
            "department":      bid.get("department", ""),
            "start_date":      bid.get("start_date", ""),
            "end_date":        bid.get("end_date", ""),
            "estimated_value": bid.get("estimated_value", ""),
            "bid_packet_type": bid.get("bid_packet_type", ""),
            "ra_no":           bid.get("ra_no", ""),
            "document_url":    bid.get("document_url", ""),
            "corrigendum_url": bid.get("corrigendum_url", ""),
            "chunk_index":     i,
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


def upsert_bids(bids: list[dict]):
    log.info(f"Upserting {len(bids)} bids into vector store...")
    for i, bid in enumerate(bids, 1):
        try:
            upsert_bid(bid)
            if i % 10 == 0:
                log.info(f"  Indexed {i}/{len(bids)}")
        except Exception as e:
            log.error(f"  Upsert failed for {bid.get('bid_no','?')}: {e}")
    log.info(
        f"Vector store upsert complete — "
        f"total chunks: {_get_collection().count()}"
    )


# =========================================================
# KEYWORD SCORING (TF-IDF style boost)
# Higher score if query terms appear in item name, dept, etc.
# =========================================================
def _keyword_score(query: str, bid: dict) -> float:
    """
    Scores 0.0 to 1.0 based on how well query keywords
    match structured bid fields.
    """
    query_words = set(query.lower().split())
    
    # Remove common stop words
    stop_words = {"for", "the", "a", "an", "and", "or", "in", "of", "is"}
    query_words -= stop_words
    
    if not query_words:
        return 0.5  # neutral if all words are stop words
    
    # Searchable fields with weights
    fields_text = {
        "full_item_name": 3.0,    # match item name heavily
        "department": 1.5,
        "bid_type": 1.0,
        "product_type": 1.0,
    }
    
    total_score = 0.0
    max_possible = sum(fields_text.values())
    
    for field, weight in fields_text.items():
        field_text = (bid.get(field, "") or "").lower()
        field_words = set(field_text.split())
        
        # Count matching words
        matches = len(query_words & field_words)
        if matches > 0:
            total_score += weight * (matches / len(query_words))
    
    # Normalize to 0.0-1.0
    return min(1.0, total_score / max_possible)


# =========================================================
# HYBRID SEARCH: semantic + keyword
# =========================================================
def search(
    query: str,
    top_k: int = RAG_TOP_K,
    filters: dict | None = None,
) -> list[dict]:
    """
    Hybrid search combining:
    - Semantic similarity (embeddings, 60% weight)
    - Keyword matching (TF-IDF style, 40% weight)
    
    Returns top_k UNIQUE bids sorted by hybrid score.
    """
    col       = _get_collection()
    total     = col.count()
    if total == 0:
        log.warning("Vector store is empty — run --reindex first")
        return []

    query_vec = embed_query(query)

    # Fetch more raw chunks than needed to account for dedup
    fetch_n = min(top_k * 4, total)

    kwargs: dict = {
        "query_embeddings": [query_vec],
        "n_results":        fetch_n,
        "include":          ["documents", "metadatas", "distances"],
    }
    if filters:
        kwargs["where"] = filters

    results   = col.query(**kwargs)
    docs      = results["documents"][0]
    metas     = results["metadatas"][0]
    distances = results["distances"][0]

    # ── Build bid result dict with HYBRID scoring ─────────────────
    seen: dict[str, dict] = {}
    
    for doc, meta, dist in zip(docs, metas, distances):
        bid_no = meta.get("bid_no", "")
        
        # Semantic score (cosine similarity)
        semantic_score = round(1 - dist, 4)
        
        # Keyword score (TF-IDF style)
        keyword_score = _keyword_score(query, meta)
        
        # Hybrid: 60% semantic + 40% keyword
        hybrid_score = (semantic_score * 0.6) + (keyword_score * 0.4)
        
        if bid_no not in seen or hybrid_score > seen[bid_no]["score"]:
            seen[bid_no] = {
                "chunk":           doc,
                "score":           round(hybrid_score, 4),
                "semantic_score":  semantic_score,
                "keyword_score":   round(keyword_score, 4),
                "bid_no":          bid_no,
                "bid_type":        meta.get("bid_type", ""),
                "product_type":    meta.get("product_type", ""),
                "full_item_name":  meta.get("full_item_name", ""),
                "quantity":        meta.get("quantity", ""),
                "department":      meta.get("department", ""),
                "start_date":      meta.get("start_date", ""),
                "end_date":        meta.get("end_date", ""),
                "estimated_value": meta.get("estimated_value", ""),
                "bid_packet_type": meta.get("bid_packet_type", ""),
                "ra_no":           meta.get("ra_no", ""),
                "document_url":    meta.get("document_url", ""),
                "corrigendum_url": meta.get("corrigendum_url", ""),
            }

    # Sort by hybrid score descending, return top_k
    output = sorted(seen.values(), key=lambda x: x["score"], reverse=True)
    return output[:top_k]


def _delete_bid_chunks(col, bid_no: str):
    try:
        col.delete(where={"bid_no": bid_no})
    except Exception:
        pass


def reindex_all(db):
    log.info("Starting full re-index from SQLite...")
    bids = db.get_all()
    upsert_bids(bids)
    log.info("Re-index complete.")


def stats() -> dict:
    col = _get_collection()
    return {
        "collection":   CHROMA_COLLECTION,
        "total_chunks": col.count(),
        "chroma_dir":   CHROMA_DIR,
    }