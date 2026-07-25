# =========================================================
# rag/vector_store.py
# Full hybrid pipeline: BGE dense + BM25 + RRF + reranker
# FIX: Reranker sigmoid normalization (was stuck at ~50%)
#      BM25 now indexes metadata card text (not raw chunks)
# =========================================================
from __future__ import annotations
import math
import chromadb
from chromadb.config import Settings as ChromaSettings
from config.settings import (
    CHROMA_DIR, CHROMA_COLLECTION, RAG_TOP_K,
    RAG_FETCH_K, RAG_DENSE_WEIGHT, RAG_BM25_WEIGHT,
    RAG_USE_RERANKER, RAG_RERANKER_MODEL,
)
from rag.embedder import build_bid_chunks, embed_texts, embed_query
from utils.logger import get_logger

log = get_logger("vector_store")

_client     = None
_collection = None
_bm25_index = None
_bm25_docs  = None
_reranker   = None


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
        log.info(f"ChromaDB ready — collection '{CHROMA_COLLECTION}' ({_collection.count()} chunks)")
    return _collection


def _get_bm25():
    global _bm25_index, _bm25_docs
    if _bm25_index is not None:
        return _bm25_index, _bm25_docs

    col   = _get_collection()
    total = col.count()
    if total == 0:
        return None, []

    result = col.get(include=["documents", "metadatas"])
    docs   = result["documents"]
    metas  = result["metadatas"]

    corpus      = []
    doc_records = []
    for doc, meta in zip(docs, metas):
        # BM25 corpus includes metadata fields so item name / dept match
        rich = (
            f"{meta.get('full_item_name','')} "
            f"{meta.get('department','')} "
            f"{meta.get('bid_type','')} "
            f"{meta.get('product_type','')} "
            f"{meta.get('bid_no','')} "
            f"{doc}"
        ).lower()
        corpus.append(rich.split())
        doc_records.append({"doc": doc, "meta": meta})

    try:
        from rank_bm25 import BM25Okapi
        _bm25_index = BM25Okapi(corpus)
        _bm25_docs  = doc_records
        log.info(f"BM25 index ready ({total} chunks).")
    except ImportError:
        log.warning("rank_bm25 not installed — pip install rank-bm25")
        _bm25_index = None
        _bm25_docs  = []

    return _bm25_index, _bm25_docs


def _get_reranker():
    global _reranker
    if _reranker is not None:
        return _reranker
    if not RAG_USE_RERANKER:
        return None
    try:
        import os
        import torch
        from sentence_transformers import CrossEncoder

        device = "cuda" if torch.cuda.is_available() else "cpu"

        # Force offline mode — same SSL fix as embedder
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")

        log.info(f"Loading reranker: {RAG_RERANKER_MODEL} on device '{device}' (offline mode)")
        _reranker = CrossEncoder(RAG_RERANKER_MODEL, device=device, local_files_only=True)
        log.info(f"Reranker ready on device '{device}'")
    except Exception as e:
        log.warning(f"Reranker load failed: {e}")
        _reranker = None
    return _reranker


def upsert_bid(bid: dict):
    global _bm25_index
    _bm25_index = None

    col    = _get_collection()
    bid_no = bid.get("bid_no") or bid.get("document_url", "unknown")
    chunks = build_bid_chunks(bid)
    if not chunks:
        log.warning(f"No chunks for {bid_no} — skipping")
        return

    _delete_bid_chunks(col, bid_no)
    ids        = [f"{bid_no}__chunk_{i}" for i in range(len(chunks))]
    embeddings = embed_texts(chunks)
    metadatas  = [
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
    col.upsert(ids=ids, embeddings=embeddings,
               documents=chunks, metadatas=metadatas)


def upsert_bids(bids: list[dict]):
    log.info(f"Upserting {len(bids)} bids into vector store...")
    for i, bid in enumerate(bids, 1):
        try:
            upsert_bid(bid)
            if i % 10 == 0:
                log.info(f"  Indexed {i}/{len(bids)}")
        except Exception as e:
            log.error(f"  Upsert failed for {bid.get('bid_no','?')}: {e}")
    log.info(f"Vector store upsert complete — total chunks: {_get_collection().count()}")


def _delete_bid_chunks(col, bid_no: str):
    try:
        col.delete(where={"bid_no": bid_no})
    except Exception:
        pass


def _rrf(rankings: list[list], k: int = 60) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranked_list in rankings:
        for rank, item_id in enumerate(ranked_list):
            scores[item_id] = scores.get(item_id, 0) + 1.0 / (k + rank + 1)
    return scores


def _sigmoid(x: float) -> float:
    """Convert raw reranker logit to 0-1 probability."""
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def search(
    query: str,
    top_k: int = RAG_TOP_K,
    filters: dict | None = None,
) -> list[dict]:
    col   = _get_collection()
    total = col.count()
    if total == 0:
        log.warning("Vector store empty — run --reindex first")
        return []

    fetch_n = min(RAG_FETCH_K, total)

    # 1. Dense retrieval
    query_vec = embed_query(query)
    kwargs: dict = {
        "query_embeddings": [query_vec],
        "n_results":        fetch_n,
        "include":          ["documents", "metadatas", "distances"],
    }
    if filters:
        kwargs["where"] = filters

    dense_result = col.query(**kwargs)
    dense_docs   = dense_result["documents"][0]
    dense_metas  = dense_result["metadatas"][0]
    dense_dists  = dense_result["distances"][0]

    chunk_map: dict[str, dict] = {}
    dense_ranking = []
    for doc, meta, dist in zip(dense_docs, dense_metas, dense_dists):
        cid = f"{meta.get('bid_no','')}__chunk_{meta.get('chunk_index',0)}"
        chunk_map[cid] = {
            "doc": doc, "meta": meta,
            "semantic_score": round(1.0 - dist, 4),
            "bm25_score": 0.0,
        }
        dense_ranking.append(cid)

    # 2. BM25 sparse retrieval
    # BM25 must respect the same filters as dense retrieval.
    # We check each candidate's metadata against the filter dict
    # before adding it to the ranking.
    bm25_ranking = []
    bm25_idx, bm25_docs_list = _get_bm25()
    if bm25_idx is not None:
        try:
            tokens = query.lower().split()
            scores = bm25_idx.get_scores(tokens)
            scored = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
            for idx, sc in scored[:fetch_n]:
                if sc <= 0:
                    continue
                rec  = bm25_docs_list[idx]
                meta = rec["meta"]

                # Apply the same metadata filters as dense retrieval
                if filters:
                    skip = False
                    for fk, fv in filters.items():
                        if meta.get(fk, "") != fv:
                            skip = True
                            break
                    if skip:
                        continue

                cid  = f"{meta.get('bid_no','')}__chunk_{meta.get('chunk_index',0)}"
                bm25_ranking.append(cid)
                norm = min(1.0, sc / 20.0)
                if cid not in chunk_map:
                    chunk_map[cid] = {
                        "doc": rec["doc"], "meta": meta,
                        "semantic_score": 0.0, "bm25_score": norm,
                    }
                else:
                    chunk_map[cid]["bm25_score"] = norm
        except Exception as e:
            log.debug(f"BM25 error: {e}")

    # 3. RRF fusion
    rrf_scores = _rrf(
        [dense_ranking, bm25_ranking] if bm25_ranking else [dense_ranking]
    )

    # 4. Dedup by bid — keep best chunk per bid
    bid_best: dict[str, dict] = {}
    for cid, rrf_sc in sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True):
        if cid not in chunk_map:
            continue
        entry  = chunk_map[cid]
        bid_no = entry["meta"].get("bid_no", "")
        if bid_no not in bid_best or rrf_sc > bid_best[bid_no]["rrf_score"]:
            bid_best[bid_no] = {**entry, "rrf_score": rrf_sc}

    candidates  = sorted(bid_best.values(), key=lambda x: x["rrf_score"], reverse=True)
    rerank_pool = candidates[:min(len(candidates), top_k * 3)]

    # 5. Cross-encoder reranker with sigmoid
    reranker = _get_reranker()
    if reranker and rerank_pool:
        try:
            pairs  = [(query, c["doc"]) for c in rerank_pool]
            logits = reranker.predict(pairs)
            for c, logit in zip(rerank_pool, logits):
                # FIX: sigmoid converts raw logit (-inf,+inf) → (0,1)
                c["rerank_score"] = _sigmoid(float(logit))
            rerank_pool.sort(key=lambda x: x["rerank_score"], reverse=True)
        except Exception as e:
            log.warning(f"Reranker error: {e}")
            for c in rerank_pool:
                c["rerank_score"] = c.get("semantic_score", 0.0)
    else:
        for c in rerank_pool:
            c["rerank_score"] = c.get("semantic_score", 0.0)

    # 6. Build output — filter by minimum score threshold
    output = []
    for c in rerank_pool[:top_k]:
        meta      = c["meta"]
        rerank_sc = c.get("rerank_score", 0.0)
        sem_sc    = c.get("semantic_score", 0.0)
        bm25_sc   = c.get("bm25_score", 0.0)
        # Weighted final: reranker dominates
        final = (rerank_sc * 0.6) + (sem_sc * 0.25) + (bm25_sc * 0.15)

        # Skip results that are pure noise (reranker stuck at neutral ~50%
        # with no semantic signal — these are BM25 false positives)
        if sem_sc == 0.0 and rerank_sc < 0.55:
            log.debug(
                f"Filtered out noise result: {meta.get('bid_no','')} "
                f"(rerank={rerank_sc:.2f}, dense=0.00)"
            )
            continue

        output.append({
            "chunk":           c["doc"],
            "score":           round(final, 4),
            "rerank_score":    round(rerank_sc, 4),
            "semantic_score":  round(sem_sc, 4),
            "bm25_score":      round(bm25_sc, 4),
            "bid_no":          meta.get("bid_no", ""),
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
        })

    # Rule B: drop results scoring less than 70% of top result
    # (handles small corpus "one match + noise filler" pattern)
    if output and len(output) > 1:
        top_score = output[0]["score"]
        cutoff    = top_score * 0.70
        original  = len(output)
        output    = [r for r in output if r["score"] >= cutoff]
        # Always return at least 1 result
        if not output:
            output = [output[0]]
        elif len(output) < original:
            log.debug(f"Filtered {original - len(output)} low-confidence results (score < {cutoff:.2%})")

    return output


def reindex_all(db):
    global _bm25_index
    _bm25_index = None
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