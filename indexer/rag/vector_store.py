# =========================================================
# indexer/rag/vector_store.py
# ChromaDB WRITE operations — used only by the indexer.
# The query module has its own read-focused vector_store.py.
# =========================================================
from __future__ import annotations
import chromadb
from chromadb.config import Settings as ChromaSettings
from shared.config.settings import CHROMA_DIR, CHROMA_PRODUCTS_COLLECTION, CHROMA_SERVICES_COLLECTION
from shared.rag.embedder import build_bid_chunks, embed_texts
from shared.utils.logger import get_logger

log = get_logger("vector_store")

_client     = None
_collections = {}


def _get_collection(product_type: str = "Product"):
    global _client, _collections
    if _client is None:
        _client = chromadb.PersistentClient(
            path=CHROMA_DIR,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    
    col_name = CHROMA_PRODUCTS_COLLECTION if "Product" in product_type else CHROMA_SERVICES_COLLECTION

    if col_name not in _collections:
        _collections[col_name] = _client.get_or_create_collection(
            name=col_name,
            metadata={"hnsw:space": "cosine"},
        )
        log.info(
            f"ChromaDB ready — collection '{col_name}' "
            f"({_collections[col_name].count()} chunks)"
        )
    return _collections[col_name]


def _delete_bid_chunks(col, bid_no: str):
    try:
        col.delete(where={"bid_no": bid_no})
    except Exception:
        pass


# ---------------------------------------------------------
# UPSERT ONE BID
# ---------------------------------------------------------
def upsert_bid(bid: dict):
    bid_no = bid.get("bid_no") or bid.get("document_url", "unknown")
    product_type = bid.get("product_type", "") or bid.get("product_name", "")
    log.info(f"  Indexing: {bid_no} to {product_type}")

    col    = _get_collection(product_type)
    chunks = build_bid_chunks(bid)
    if not chunks:
        log.warning(f"  No chunks for {bid_no} — skipping")
        return

    _delete_bid_chunks(col, bid_no)

    ids        = [f"{bid_no}__chunk_{i}" for i in range(len(chunks))]
    embeddings = embed_texts(chunks)
    metadatas  = [
        {
            "bid_no":           bid_no,
            "bid_type":         bid.get("bid_type", "") or bid.get("tender_type", ""),
            "product_type":     bid.get("product_type", "") or bid.get("product_name", ""),
            "full_item_name":   bid.get("full_item_name", ""),
            "quantity":         bid.get("quantity", ""),
            "department":       bid.get("department", "") or bid.get("authority", ""),
            "authority":        bid.get("authority", "") or bid.get("department", ""),
            "sector":           bid.get("sector", ""),
            "state":            bid.get("state", ""),
            "city":             bid.get("city", ""),
            "status":           bid.get("status", "") or bid.get("tender_status", ""),
            "procurement_type": bid.get("procurement_type", ""),
            "start_date":       bid.get("start_date", ""),
            "end_date":         bid.get("end_date", "") or bid.get("due_date", ""),
            "estimated_value":  bid.get("estimated_value", "") or bid.get("tender_value", ""),
            "bid_packet_type":  bid.get("bid_packet_type", ""),
            "ra_no":            bid.get("ra_no", ""),
            "document_url":     bid.get("document_url", ""),
            "corrigendum_url":  bid.get("corrigendum_url", ""),
            "chunk_index":      i,
        }
        for i in range(len(chunks))
    ]

    col.upsert(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)
    log.info(f"  Indexed {len(chunks)} chunks for {bid_no}")


# ---------------------------------------------------------
# BATCH UPSERT
# ---------------------------------------------------------
def upsert_bids(bids: list[dict]):
    log.info(f"Batch indexing {len(bids)} bids...")
    for i, bid in enumerate(bids, 1):
        try:
            upsert_bid(bid)
            if i % 10 == 0:
                log.info(f"  Progress: {i}/{len(bids)}")
        except Exception as e:
            log.error(f"  Failed for {bid.get('bid_no','?')}: {e}")
    log.info(f"Batch complete — total chunks: {_get_collection().count()}")


# ---------------------------------------------------------
# FULL REINDEX  (rebuilds from scratch)
# ---------------------------------------------------------
def reindex_all(bids: list[dict]):
    log.info(f"Full reindex: {len(bids)} bids")
    upsert_bids(bids)
    log.info("Reindex complete.")


# ---------------------------------------------------------
# STATS
# ---------------------------------------------------------
def stats() -> dict:
    return {
        "collections":  [CHROMA_PRODUCTS_COLLECTION, CHROMA_SERVICES_COLLECTION],
        "chroma_dir":   CHROMA_DIR,
        "product_chunks": _get_collection("Product").count(),
        "service_chunks": _get_collection("Service").count(),
    }
