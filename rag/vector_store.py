# =========================================================
# rag/vector_store.py
# Hybrid retrieval pipeline:
#
#   step 1  ─ Dense retrieval        (ChromaDB / BGE embeddings)
#   step 2  ─ Sparse retrieval       (BM25 over indexed chunks)
#   step 3  ─ Fuse                   (Reciprocal Rank Fusion)
#   step 4  ─ Cross-encoder rerank   (BAAI/bge-reranker-base)
#
# This combination is the standard 2024–2026 RAG recipe and
# is what lifts retrieval scores from ~20% to 70–90% for true
# matches (see RAG_TUNING_GUIDE.md).
# =========================================================
from __future__ import annotations
import re
import threading
import chromadb
from chromadb.config import Settings as ChromaSettings
from config.settings import (
    CHROMA_DIR, CHROMA_COLLECTION, RAG_TOP_K,
    RAG_BM25_WEIGHT, RAG_DENSE_WEIGHT, RAG_FETCH_K,
    RAG_USE_RERANKER, RAG_RERANKER_MODEL,
)
from rag.embedder import (
    build_bid_chunks,
    embed_texts,
    embed_query,
)
from utils.logger import get_logger

log = get_logger("vector_store")

_client = None
_collection = None

# Lazy singletons for BM25 + reranker
_bm25 = None                  # rank_bm25.BM25Okapi
_bm25_ids: list[str] = []     # chunk-ids aligned with _bm25 corpus
_bm25_lock = threading.Lock()
_reranker = None


# =========================================================
# CHROMA COLLECTION
# =========================================================
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
    col = _get_collection()
    bid_no = bid.get("bid_no") or bid.get("document_url", "unknown")

    chunks = build_bid_chunks(bid)
    if not chunks:
        log.warning(f"No chunks for {bid_no} — skipping")
        return

    _delete_bid_chunks(col, bid_no)

    ids = [f"{bid_no}__chunk_{i}" for i in range(len(chunks))]
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

    # invalidate caches so the new chunks are seen
    _invalidate_caches()
    log.debug(f"Upserted {len(chunks)} chunks for {bid_no}")


def upsert_bids(bids: list[dict]):
    log.info(f"Upserting {len(bids)} bids into vector store...")
    for i, bid in enumerate(bids, 1):
        try:
            upsert_bid(bid)
            if i % 10 == 0:
                log.info(f"  Indexed {i}/{len(bids)}")
        except Exception as e:
            log.error(f"  Upsert failed for {bid.get('bid_no', '?')}: {e}")
    log.info(
        f"Vector store upsert complete — "
        f"total chunks: {_get_collection().count()}"
    )


# =========================================================
# BM25 INDEX  (built lazily over every chunk in the collection)
# =========================================================
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokenise(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _build_bm25_index():
    """Pulls every chunk from Chroma and builds a BM25Okapi index."""
    global _bm25, _bm25_ids
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        log.warning("rank_bm25 not installed — sparse retrieval disabled. "
                    "Run: pip install rank-bm25")
        _bm25 = None
        _bm25_ids = []
        return

    col = _get_collection()
    n = col.count()
    if n == 0:
        _bm25 = None
        _bm25_ids = []
        return

    log.info(f"Building BM25 index over {n} chunks...")
    # Chroma's `get` returns ids + documents + metadatas for the whole collection
    res = col.get(include=["documents", "metadatas"])
    ids = res.get("ids", []) or []
    docs = res.get("documents", []) or []
    metas = res.get("metadatas", []) or []

    # For BM25 corpus we add the structured metadata fields too —
    # this hugely boosts keyword recall on bid_no / item / dept.
    corpus_tokens = []
    for doc, meta in zip(docs, metas):
        meta = meta or {}
        blob = " ".join([
            doc or "",
            meta.get("bid_no", "") or "",
            meta.get("ra_no", "") or "",
            meta.get("full_item_name", "") or "",
            meta.get("department", "") or "",
            meta.get("bid_type", "") or "",
            meta.get("product_type", "") or "",
        ])
        corpus_tokens.append(_tokenise(blob))

    _bm25 = BM25Okapi(corpus_tokens)
    _bm25_ids = ids
    log.info(f"BM25 index ready ({len(ids)} chunks).")


def _ensure_bm25():
    with _bm25_lock:
        if _bm25 is None and not _bm25_ids:
            _build_bm25_index()


def _invalidate_caches():
    global _bm25, _bm25_ids
    with _bm25_lock:
        _bm25 = None
        _bm25_ids = []


# =========================================================
# RERANKER  (cross-encoder)
# =========================================================
def _get_reranker():
    global _reranker
    if _reranker is None and RAG_USE_RERANKER:
        try:
            from sentence_transformers import CrossEncoder
            log.info(f"Loading reranker: {RAG_RERANKER_MODEL}")
            _reranker = CrossEncoder(RAG_RERANKER_MODEL)
            log.info("Reranker ready")
        except Exception as e:
            log.warning(f"Reranker unavailable ({e}) — skipping rerank")
            _reranker = False  # tri-state: None=untried, False=disabled
    return _reranker if _reranker else None


# =========================================================
# RRF (Reciprocal Rank Fusion)
# =========================================================
def _rrf(ranked_lists: list[list[str]], k: int = 60) -> dict[str, float]:
    """Returns id -> fused score. Higher is better."""
    scores: dict[str, float] = {}
    for ranking in ranked_lists:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


# =========================================================
# HYBRID SEARCH
# =========================================================
def search(
    query: str,
    top_k: int = RAG_TOP_K,
    filters: dict | None = None,
) -> list[dict]:
    """
    Hybrid retrieval:
      dense (Chroma)  +  sparse (BM25)  ─►  RRF fuse  ─►
      cross-encoder rerank  ─►  dedup by bid_no  ─►  top_k.
    """
    col = _get_collection()
    if col.count() == 0:
        log.warning("Vector store is empty — run --reindex first")
        return []

    fetch_k = max(RAG_FETCH_K, top_k * 6)

    # ── 1. DENSE ──────────────────────────────────────────
    q_vec = embed_query(query)
    kwargs = {
        "query_embeddings": [q_vec],
        "n_results":        min(fetch_k, col.count()),
        "include":          ["documents", "metadatas", "distances"],
    }
    if filters:
        kwargs["where"] = filters

    dense_res = col.query(**kwargs)
    dense_ids = dense_res.get("ids", [[]])[0]
    dense_docs = dense_res["documents"][0]
    dense_metas = dense_res["metadatas"][0]
    dense_dists = dense_res["distances"][0]

    # id -> (doc, meta, semantic_score)
    by_id: dict[str, dict] = {}
    for cid, doc, meta, dist in zip(dense_ids, dense_docs, dense_metas, dense_dists):
        # Chroma cosine distance ∈ [0, 2] → similarity ∈ [-1, 1]
        sim = max(0.0, 1.0 - float(dist))
        by_id[cid] = {
            "doc":            doc,
            "meta":           meta or {},
            "semantic_score": round(sim, 4),
        }

    # ── 2. SPARSE (BM25) ──────────────────────────────────
    _ensure_bm25()
    bm25_ranked: list[str] = []
    bm25_scores: dict[str, float] = {}
    if _bm25 is not None and _bm25_ids:
        try:
            scores = _bm25.get_scores(_tokenise(query))
            # Sort by score desc
            order = sorted(
                range(len(scores)),
                key=lambda i: scores[i],
                reverse=True,
            )[:fetch_k]
            bm25_ranked = [_bm25_ids[i] for i in order if scores[i] > 0]
            # min-max normalise BM25 scores into 0..1 for display
            top_score = scores[order[0]] if order else 0.0
            if top_score > 0:
                bm25_scores = {
                    _bm25_ids[i]: float(scores[i]) / top_score for i in order
                }
        except Exception as e:
            log.debug(f"BM25 query failed: {e}")

    # Hydrate any BM25 hits Chroma didn't surface
    missing_ids = [cid for cid in bm25_ranked if cid not in by_id]
    if missing_ids:
        try:
            hydr = col.get(
                ids=missing_ids,
                include=["documents", "metadatas"],
            )
            for cid, doc, meta in zip(
                hydr.get("ids", []),
                hydr.get("documents", []),
                hydr.get("metadatas", []),
            ):
                by_id[cid] = {
                    "doc":            doc,
                    "meta":           meta or {},
                    "semantic_score": 0.0,
                }
        except Exception as e:
            log.debug(f"BM25 hydrate failed: {e}")

    # ── 3. FUSE  (RRF) ────────────────────────────────────
    dense_only_ranking = list(dense_ids)
    rrf_scores = _rrf([dense_only_ranking, bm25_ranked])

    fused = []
    for cid, score in rrf_scores.items():
        if cid not in by_id:
            continue
        fused.append({
            "id":             cid,
            "fused_score":    score,
            "bm25_score":     round(bm25_scores.get(cid, 0.0), 4),
            **by_id[cid],
        })

    # Take top N for reranking
    fused.sort(key=lambda x: x["fused_score"], reverse=True)
    top_for_rerank = fused[: max(top_k * 4, 20)]

    # ── 4. CROSS-ENCODER RERANK ──────────────────────────
    reranker = _get_reranker()
    if reranker and top_for_rerank:
        pairs = [(query, c["doc"]) for c in top_for_rerank]
        try:
            ce_scores = reranker.predict(pairs)
            # CE scores are raw logits — squash to 0..1 with sigmoid
            import math
            for c, s in zip(top_for_rerank, ce_scores):
                c["rerank_score"] = round(1.0 / (1.0 + math.exp(-float(s))), 4)
            top_for_rerank.sort(key=lambda x: x["rerank_score"], reverse=True)
        except Exception as e:
            log.debug(f"Rerank failed: {e}")
            for c in top_for_rerank:
                c["rerank_score"] = c["semantic_score"]
    else:
        for c in top_for_rerank:
            c["rerank_score"] = c["semantic_score"]

    # ── 5. DEDUP PER BID  +  FINAL FORMAT ────────────────
    best_per_bid: dict[str, dict] = {}
    for c in top_for_rerank:
        meta = c["meta"]
        bid_no = meta.get("bid_no", "") or c["id"]
        final_score = c["rerank_score"]
        if bid_no not in best_per_bid or final_score > best_per_bid[bid_no]["score"]:
            best_per_bid[bid_no] = {
                "chunk":           c["doc"],
                "score":           round(final_score, 4),
                "semantic_score":  c["semantic_score"],
                "bm25_score":      c["bm25_score"],
                "rerank_score":    final_score,
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

    output = sorted(best_per_bid.values(), key=lambda x: x["score"], reverse=True)
    return output[:top_k]


# =========================================================
# HOUSEKEEPING
# =========================================================
def _delete_bid_chunks(col, bid_no: str):
    try:
        col.delete(where={"bid_no": bid_no})
    except Exception:
        pass


def reindex_all(db):
    log.info("Starting full re-index from SQLite...")
    bids = db.get_all()
    upsert_bids(bids)
    _invalidate_caches()
    _ensure_bm25()
    log.info("Re-index complete.")


def stats() -> dict:
    col = _get_collection()
    return {
        "collection":   CHROMA_COLLECTION,
        "total_chunks": col.count(),
        "chroma_dir":   CHROMA_DIR,
    }


# Backwards-compat: some old callers import _keyword_score
def _keyword_score(query: str, bid: dict) -> float:  # pragma: no cover
    return 0.0