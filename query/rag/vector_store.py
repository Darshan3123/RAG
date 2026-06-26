# =========================================================
# query/rag/vector_store.py
# ChromaDB READ operations + hybrid retrieval pipeline.
# Dense (BGE) + BM25 + RRF fusion + cross-encoder reranker.
# =========================================================
from __future__ import annotations
import math
import chromadb
from chromadb.config import Settings as ChromaSettings
from shared.config.settings import (
    CHROMA_DIR, CHROMA_PRODUCTS_COLLECTION, CHROMA_SERVICES_COLLECTION, RAG_TOP_K,
    RAG_FETCH_K, RAG_DENSE_WEIGHT, RAG_BM25_WEIGHT,
    RAG_USE_RERANKER, RAG_RERANKER_MODEL,
)
from shared.rag.embedder import embed_query
from shared.utils.logger import get_logger

log = get_logger("vector_store")

# Reranker weight — remainder split between dense and bm25
_RERANKER_WEIGHT = float(__import__('os').getenv("RAG_RERANKER_WEIGHT", "0.60"))
_DENSE_WEIGHT    = RAG_DENSE_WEIGHT   # default 0.6 → used as fraction of non-reranker weight
_BM25_WEIGHT     = RAG_BM25_WEIGHT    # default 0.4 → used as fraction of non-reranker weight

_client     = None
_collections = {}
_bm25_indexes = {}
_bm25_docs  = {}
_reranker   = None


def _get_collection(collection_name: str):
    global _client, _collections
    if _client is None:
        _client = chromadb.PersistentClient(
            path=CHROMA_DIR,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    if collection_name not in _collections:
        _collections[collection_name] = _client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        log.info(
            f"ChromaDB ready — collection '{collection_name}' "
            f"({_collections[collection_name].count()} chunks)"
        )
    return _collections[collection_name]


def _get_bm25(collection_name: str):
    global _bm25_indexes, _bm25_docs
    if collection_name in _bm25_indexes:
        return _bm25_indexes[collection_name], _bm25_docs[collection_name]

    col   = _get_collection(collection_name)
    total = col.count()
    if total == 0:
        return None, []

    result = col.get(include=["documents", "metadatas"])
    docs   = result["documents"]
    metas  = result["metadatas"]

    corpus      = []
    doc_records = []
    for doc, meta in zip(docs, metas):
        # BM25 indexes ONLY structured metadata fields — NOT the raw PDF body chunks.
        # This prevents department names like "Military Affairs" from firing on every
        # military bid regardless of what the item actually is.
        # Item name gets 3× weight — it's the most discriminative signal.
        item = meta.get('full_item_name', '')
        rich = (
            f"{item} {item} {item} "          # 3× item name weight
            f"{meta.get('bid_no','')} "        # exact bid number lookup
            f"{meta.get('bid_type','')} "
            f"{meta.get('product_type','')} "
            f"{meta.get('sector','')} "
            f"{meta.get('state','')} "
            f"{meta.get('city','')} "
            f"{meta.get('status','')} "
            f"{meta.get('procurement_type','')} "
            f"{meta.get('category','')} "
            f"{meta.get('sub_category','')} "
            f"{meta.get('department','')} "    # dept once — not repeated
        ).lower()
        corpus.append(rich.split())
        doc_records.append({"doc": doc, "meta": meta})

    try:
        from rank_bm25 import BM25Okapi
        _bm25_indexes[collection_name] = BM25Okapi(corpus)
        _bm25_docs[collection_name]  = doc_records
        log.info(f"BM25 index ready ({total} chunks).")
    except ImportError:
        log.warning("rank_bm25 not installed — pip install rank-bm25")
        _bm25_indexes[collection_name] = None
        _bm25_docs[collection_name]  = []

    return _bm25_indexes[collection_name], _bm25_docs[collection_name]


def _get_reranker():
    global _reranker
    if _reranker is not None:
        return _reranker
    if not RAG_USE_RERANKER:
        return None
    try:
        import os
        from sentence_transformers import CrossEncoder
        offline = os.getenv("HF_OFFLINE", "false").lower() in ("1", "true", "yes")
        if offline:
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            os.environ["HF_DATASETS_OFFLINE"]  = "1"
            os.environ["HF_HUB_OFFLINE"]       = "1"
        log.info(f"Loading reranker: {RAG_RERANKER_MODEL}")
        _reranker = CrossEncoder(RAG_RERANKER_MODEL, local_files_only=offline)
        log.info("Reranker ready")
    except Exception as e:
        log.warning(f"Reranker load failed: {e}")
        _reranker = None
    return _reranker


def _rrf(rankings: list[list], k: int = 30) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranked_list in rankings:
        for rank, item_id in enumerate(ranked_list):
            scores[item_id] = scores.get(item_id, 0) + 1.0 / (k + rank + 1)
    return scores


def _sigmoid(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def search(
    query: str,
    top_k: int = RAG_TOP_K,
    filters: dict | None = None,
    collection_name: str = None,
) -> list[dict]:
    if not collection_name:
        collection_name = CHROMA_PRODUCTS_COLLECTION
    col   = _get_collection(collection_name)
    total = col.count()
    if total == 0:
        log.warning("Vector store empty — run indexer: python main.py --index-new")
        return []

    fetch_n   = min(RAG_FETCH_K, total)
    query_vec = embed_query(query)

    kwargs: dict = {
        "query_embeddings": [query_vec],
        "n_results":        fetch_n,
        "include":          ["documents", "metadatas", "distances"],
    }
    if filters:
        kwargs["where"] = filters if len(filters) == 1 else {"$and": [{k: v} for k, v in filters.items()]}

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

    bm25_ranking = []
    bm25_idx, bm25_docs_list = _get_bm25(collection_name)
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
                if filters:
                    skip = any(meta.get(fk, "") != fv for fk, fv in filters.items())
                    if skip:
                        continue
                cid  = f"{meta.get('bid_no','')}__chunk_{meta.get('chunk_index',0)}"
                bm25_ranking.append(cid)
                norm = min(1.0, sc / 10.0)
                if cid not in chunk_map:
                    chunk_map[cid] = {"doc": rec["doc"], "meta": meta,
                                      "semantic_score": 0.0, "bm25_score": norm}
                else:
                    chunk_map[cid]["bm25_score"] = norm
        except Exception as e:
            log.debug(f"BM25 error: {e}")

    rrf_scores = _rrf([dense_ranking, bm25_ranking] if bm25_ranking else [dense_ranking])

    bid_best: dict[str, dict] = {}
    for cid, rrf_sc in sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True):
        if cid not in chunk_map:
            continue
        entry  = chunk_map[cid]
        bid_no = entry["meta"].get("bid_no", "")
        chunk_idx = entry["meta"].get("chunk_index", 99)
        # Prefer chunk[0] (metadata card) for reranking — it has the structured
        # item name, sector, dept which the reranker needs to judge relevance.
        # Only replace if this chunk has a better RRF score AND the current best
        # is not chunk[0].
        if bid_no not in bid_best:
            bid_best[bid_no] = {**entry, "rrf_score": rrf_sc}
        else:
            current = bid_best[bid_no]
            current_idx = current["meta"].get("chunk_index", 99)
            # Always prefer chunk[0] over any other chunk
            if chunk_idx == 0 and current_idx != 0:
                bid_best[bid_no] = {**entry, "rrf_score": rrf_sc}
            elif chunk_idx != 0 and current_idx == 0:
                pass  # keep existing chunk[0]
            elif rrf_sc > current["rrf_score"]:
                bid_best[bid_no] = {**entry, "rrf_score": rrf_sc}

    candidates  = sorted(bid_best.values(), key=lambda x: x["rrf_score"], reverse=True)
    rerank_pool = candidates[:min(len(candidates), top_k * 4)]

    reranker = _get_reranker()
    if reranker and rerank_pool:
        try:
            def _rerank_doc(c: dict) -> str:
                meta   = c["meta"]
                # Include sector prominently — helps reranker score sector-based queries
                parts = filter(None, [
                    meta.get("sector", ""),
                    meta.get("department", "") or meta.get("authority", ""),
                    meta.get("bid_type", ""),
                    meta.get("procurement_type", ""),
                    meta.get("state", ""),
                    meta.get("status", ""),
                ])
                prefix = " | ".join(parts)
                # Use only chunk[0] (metadata card) for reranking — it's the most structured
                # Raw PDF chunks add noise for broad queries
                body = c["doc"][:600]
                return f"{prefix} || {body}".strip() if prefix else body

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

    output = []
    for c in rerank_pool[:top_k]:
        meta      = c["meta"]
        rerank_sc = c.get("rerank_score", 0.0)
        sem_sc    = c.get("semantic_score", 0.0)
        bm25_sc   = c.get("bm25_score", 0.0)

        # The reranker score IS the relevance score — it's a calibrated cross-encoder.
        # Dense and BM25 are retrieval signals used to get candidates; they don't
        # improve accuracy when blended into the final score.
        # We show the reranker score as the primary "score", with dense/bm25 for info.
        final = rerank_sc

        # Drop results the reranker says are not relevant.
        # We lowered the threshold to 0.40 to be more forgiving for semantic matches
        rerank_cutoff = 0.40 if filters else 0.45
        if rerank_sc < rerank_cutoff:
            continue

        output.append({
            "chunk":            c["doc"],
            "score":            round(final, 4),
            "rerank_score":     round(rerank_sc, 4),
            "semantic_score":   round(sem_sc, 4),
            "bm25_score":       round(bm25_sc, 4),
            "bid_no":           meta.get("bid_no", ""),
            "bid_type":         meta.get("bid_type", ""),
            "product_type":     meta.get("product_type", ""),
            "full_item_name":   meta.get("full_item_name", ""),
            "quantity":         meta.get("quantity", ""),
            "department":       meta.get("department", ""),
            "authority":        meta.get("authority", ""),
            "sector":           meta.get("sector", ""),
            "state":            meta.get("state", ""),
            "city":             meta.get("city", ""),
            "status":           meta.get("status", ""),
            "procurement_type": meta.get("procurement_type", ""),
            "start_date":       meta.get("start_date", ""),
            "end_date":         meta.get("end_date", ""),
            "estimated_value":  meta.get("estimated_value", ""),
            "bid_packet_type":  meta.get("bid_packet_type", ""),
            "ra_no":            meta.get("ra_no", ""),
            "document_url":     meta.get("document_url", ""),
            "corrigendum_url":  meta.get("corrigendum_url", ""),
        })

    # Drop the bottom tail — anything below 80% of the top reranker score is noise.
    # Only apply when we have more than 3 results so focused queries aren't over-trimmed.
    if len(output) > 3:
        top_rerank = output[0]["rerank_score"]
        cutoff     = top_rerank * 0.80
        trimmed    = [r for r in output if r["rerank_score"] >= cutoff]
        output     = trimmed if len(trimmed) >= 1 else output

    return output


def stats() -> dict:
    return {
        "collections":  [CHROMA_PRODUCTS_COLLECTION, CHROMA_SERVICES_COLLECTION],
        "chroma_dir":   CHROMA_DIR,
        "product_chunks": _get_collection(CHROMA_PRODUCTS_COLLECTION).count(),
        "service_chunks": _get_collection(CHROMA_SERVICES_COLLECTION).count(),
    }
