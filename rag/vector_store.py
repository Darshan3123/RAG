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
        # BM25 corpus includes metadata fields so item name / dept /
        # sector / state / status all match on keyword queries
        rich = (
            f"{meta.get('full_item_name','')} "
            f"{meta.get('department','')} "
            f"{meta.get('bid_type','')} "
            f"{meta.get('product_type','')} "
            f"{meta.get('bid_no','')} "
            f"{meta.get('sector','')} "
            f"{meta.get('state','')} "
            f"{meta.get('city','')} "
            f"{meta.get('status','')} "
            f"{meta.get('authority','')} "
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
        from sentence_transformers import CrossEncoder

        # Force offline mode — same SSL fix as embedder
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")

        log.info(f"Loading reranker: {RAG_RERANKER_MODEL} (offline mode)")
        _reranker = CrossEncoder(RAG_RERANKER_MODEL, local_files_only=True)
        log.info("Reranker ready")
    except Exception as e:
        log.warning(f"Reranker load failed: {e}")
        _reranker = None
    return _reranker


def upsert_bid(bid: dict):
    global _bm25_index
    _bm25_index = None

    bid_no = bid.get("bid_no") or bid.get("document_url", "unknown")
    log.info(f"  [vector_store] Starting upsert for {bid_no}")
    
    try:
        col    = _get_collection()
        log.info(f"  [vector_store] Collection obtained")
        
        chunks = build_bid_chunks(bid)
        log.info(f"  [vector_store] Built {len(chunks)} chunks")
        
        if not chunks:
            log.warning(f"  [vector_store] No chunks for {bid_no} — skipping")
            return

        _delete_bid_chunks(col, bid_no)
        log.info(f"  [vector_store] Deleted old chunks for {bid_no}")
        
        ids        = [f"{bid_no}__chunk_{i}" for i in range(len(chunks))]
        
        log.info(f"  [vector_store] Embedding {len(chunks)} chunks...")
        embeddings = embed_texts(chunks)
        log.info(f"  [vector_store] Embeddings complete")
        
        metadatas  = [
            {
                "bid_no":          bid_no,
                "bid_type":        bid.get("bid_type", "") or bid.get("tender_type", ""),
                "product_type":    bid.get("product_type", "") or bid.get("product_name", ""),
                "full_item_name":  bid.get("full_item_name", ""),
                "quantity":        bid.get("quantity", ""),
                "department":      bid.get("department", "") or bid.get("authority", ""),
                "authority":       bid.get("authority", "") or bid.get("department", ""),
                "sector":          bid.get("sector", ""),
                "state":           bid.get("state", ""),
                "city":            bid.get("city", ""),
                "status":          bid.get("status", "") or bid.get("tender_status", ""),
                "procurement_type": bid.get("procurement_type", ""),
                "start_date":      bid.get("start_date", ""),
                "end_date":        bid.get("end_date", "") or bid.get("due_date", ""),
                "estimated_value": bid.get("estimated_value", "") or bid.get("tender_value", ""),
                "bid_packet_type": bid.get("bid_packet_type", ""),
                "ra_no":           bid.get("ra_no", ""),
                "document_url":    bid.get("document_url", ""),
                "corrigendum_url": bid.get("corrigendum_url", ""),
                "chunk_index":     i,
            }
            for i in range(len(chunks))
        ]
        
        log.info(f"  [vector_store] Upserting to ChromaDB...")
        col.upsert(ids=ids, embeddings=embeddings,
                   documents=chunks, metadatas=metadatas)
        log.info(f"  [vector_store] Upsert complete for {bid_no}")
    except Exception as e:
        log.error(f"  [vector_store] ERROR during upsert for {bid_no}: {e}", exc_info=True)
        raise


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


def _rrf(rankings: list[list], k: int = 30) -> dict[str, float]:
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
        # ChromaDB requires $and when multiple conditions are present
        if len(filters) == 1:
            kwargs["where"] = filters
        else:
            kwargs["where"] = {"$and": [{k: v} for k, v in filters.items()]}

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
                # Normalise: divisor of 10 maps typical scores (5-15) to 0.5-1.0
                # Lower divisor than before so strong keyword matches aren't suppressed
                norm = min(1.0, sc / 10.0)
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
    # Use top_k * 4 for reranking pool to ensure BM25-boosted bids
    # with lower dense ranks still get a chance to surface
    rerank_pool = candidates[:min(len(candidates), top_k * 4)]

    # 5. Cross-encoder reranker with sigmoid
    # Include key metadata in the reranker input so state/sector/dept
    # queries score correctly even when the PDF text lacks those words.
    reranker = _get_reranker()
    if reranker and rerank_pool:
        try:
            def _rerank_doc(c: dict) -> str:
                meta = c["meta"]
                prefix = " | ".join(filter(None, [
                    meta.get("sector", ""),
                    meta.get("state", ""),
                    meta.get("city", ""),
                    meta.get("department", "") or meta.get("authority", ""),
                    meta.get("status", ""),
                    meta.get("procurement_type", ""),
                ]))
                body = c["doc"]
                return f"{prefix} {body}".strip() if prefix else body

            pairs  = [(query, _rerank_doc(c)) for c in rerank_pool]
            logits = reranker.predict(pairs)
            for c, logit in zip(rerank_pool, logits):
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
        # Weighted final: reranker dominates.
        # For BM25-only hits (sem_sc=0), shift weight to rerank+bm25.
        if sem_sc == 0.0:
            final = (rerank_sc * 0.65) + (bm25_sc * 0.35)
        else:
            final = (rerank_sc * 0.6) + (sem_sc * 0.25) + (bm25_sc * 0.15)

        # Skip results that are pure noise (reranker stuck at neutral ~50%
        # with no semantic signal — these are BM25 false positives).
        # Exception: keep BM25-only hits when the BM25 score is strong
        # (≥ 0.35 normalised) — this covers state/sector keyword matches
        # where the PDF text doesn't contain those words but metadata does.
        # Relax threshold when a hard filter is active.
        noise_threshold = 0.45 if filters else 0.55
        strong_bm25 = bm25_sc >= 0.35  # ~7/20 raw BM25 score
        if sem_sc == 0.0 and rerank_sc < noise_threshold and not strong_bm25:
            log.debug(
                f"Filtered out noise result: {meta.get('bid_no','')} "
                f"(rerank={rerank_sc:.2f}, dense=0.00, bm25={bm25_sc:.2f})"
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
            "authority":       meta.get("authority", ""),
            "sector":          meta.get("sector", ""),
            "state":           meta.get("state", ""),
            "city":            meta.get("city", ""),
            "status":          meta.get("status", ""),
            "procurement_type": meta.get("procurement_type", ""),
            "start_date":      meta.get("start_date", ""),
            "end_date":        meta.get("end_date", ""),
            "estimated_value": meta.get("estimated_value", ""),
            "bid_packet_type": meta.get("bid_packet_type", ""),
            "ra_no":           meta.get("ra_no", ""),
            "document_url":    meta.get("document_url", ""),
            "corrigendum_url": meta.get("corrigendum_url", ""),
        })

    # Score normalization: rescale so the top result anchors at a
    # meaningful percentage.
    #
    # For FILTERED queries: always rescale to 85% (filter guarantees
    # correctness, score reflects relative rank within the pool).
    #
    # For FREE-TEXT queries: rescale only when the top rerank score
    # signals real relevance (≥ 0.60). This prevents inflating truly
    # irrelevant results while making genuine matches show 65-85%.
    if output:
        top_raw    = output[0]["score"]
        top_rerank = output[0].get("rerank_score", 0.0)
        if filters:
            # Hard filter active — always rescale to 85%
            target = 0.85
            if top_raw > 0:
                scale = target / top_raw
                for r in output:
                    r["score"]          = round(min(r["score"]          * scale, 1.0), 4)
                    r["rerank_score"]   = round(min(r["rerank_score"]   * scale, 1.0), 4)
                    r["semantic_score"] = round(min(r["semantic_score"] * scale, 1.0), 4)
        elif top_rerank >= 0.52:
            # Free-text query with confident top result — rescale to 75%
            target = 0.75
            if top_raw > 0:
                scale = target / top_raw
                for r in output:
                    r["score"]          = round(min(r["score"]          * scale, 1.0), 4)
                    r["rerank_score"]   = round(min(r["rerank_score"]   * scale, 1.0), 4)
                    r["semantic_score"] = round(min(r["semantic_score"] * scale, 1.0), 4)
        # else: low-confidence results — show raw scores (don't inflate)

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