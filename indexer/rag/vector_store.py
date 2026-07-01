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
def upsert_bid(bid_doc: dict):
    b = bid_doc.get("bid", {})
    card = bid_doc.get("card", {})
    pdf = bid_doc.get("pdf", {})
    norm = bid_doc.get("normalized", {})
    
    bid_no = b.get("bid_no") or "unknown"
    product_type = b.get("product_type", "")
    log.info(f"  Indexing: {bid_no} to {product_type}")

    col    = _get_collection(product_type)
    chunks = build_bid_chunks(bid_doc)
    if not chunks:
        log.warning(f"  No chunks for {bid_no} — skipping")
        return

    _delete_bid_chunks(col, bid_no)

    ids        = [f"{bid_no}__chunk_{i}" for i in range(len(chunks))]
    embeddings = embed_texts(chunks)
    
    card_items = card.get("items") or []
    c_item = card_items[0] if card_items else {}
    depts = pdf.get("departments") or []
    dept = depts[0] if depts else {}
    ra = pdf.get("ra", {})
    ae = ra.get("auto_extension", {})
    
    metadatas  = [
        {
            "bid_no":           bid_no,
            "bid_type":         b.get("bid_type", ""),
            "product_type":     b.get("product_type", ""),
            "base_type":        b.get("base_type", ""),
            "full_item_name":   str(c_item.get("name", "") or ""),
            "quantity":         str(c_item.get("quantity", "") or ""),
            "department":       str(dept.get("department_name", "") or ""),
            "state":            str(dept.get("ministry_state_name", "") or ""),
            "city":             str(dept.get("office_name", "") or ""),
            "status":           str(norm.get("status", "") or ""),
            "start_date":       str(card.get("start_datetime", "") or ""),
            "end_date":         str(card.get("end_datetime", "") or ""),
            "estimated_value":  str(norm.get("tender_value", "") or ""),
            "document_url":     str(card.get("bid_pdf_url", "") or ""),
            "ra_document_url":  str(card.get("ra_pdf_url", "") or ""),
            "ra_start":         str(ra.get("ra_start_datetime", "") or ""),
            "ra_end":           str(ra.get("ra_end_datetime", "") or ""),
            "ra_enabled":       str(ra.get("bid_to_ra_enabled", False)),
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
