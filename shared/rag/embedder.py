# =========================================================
# shared/rag/embedder.py
# Text → vector embeddings using sentence-transformers.
# Lives in shared/ because BOTH indexer and query need it
# with the exact same model so vectors are compatible.
#
# Indexer  uses: build_bid_chunks(), embed_texts()
# Query    uses: embed_query()
# Both     use: prewarm_model()
# =========================================================
from __future__ import annotations
import re
from shared.config.settings import (
    RAG_EMBEDDING_MODEL,
    RAG_CHUNK_SIZE,
    RAG_CHUNK_OVERLAP,
)
from shared.utils.logger import get_logger

log = get_logger("embedder")

_model = None

# BGE retrieval instruction prefix (recommended by model authors).
# Applied automatically when the model name contains 'bge'.
_BGE_QUERY_PROMPT = (
    "Represent this sentence for searching relevant passages: "
)


def _is_bge() -> bool:
    return "bge" in RAG_EMBEDDING_MODEL.lower()


def _get_model():
    global _model
    if _model is None:
        import os
        from sentence_transformers import SentenceTransformer

        offline = os.getenv("HF_OFFLINE", "false").lower() in ("1", "true", "yes")
        if offline:
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            os.environ["HF_DATASETS_OFFLINE"]  = "1"
            os.environ["HF_HUB_OFFLINE"]       = "1"

        mode = "offline" if offline else "online"
        log.info(f"Loading embedding model: {RAG_EMBEDDING_MODEL} ({mode})")
        log.info("  This may take 60-90 seconds on first load...")
        _model = SentenceTransformer(RAG_EMBEDDING_MODEL, local_files_only=offline)
        log.info("Embedding model ready")
    return _model


def prewarm_model():
    """Pre-load the model and run a test encode to avoid cold-start delay."""
    log.info("Pre-warming embedding model...")
    model = _get_model()
    model.encode(["Test embedding to warm up the model"], show_progress_bar=False)
    log.info("Embedding model pre-warmed and ready")


# ---------------------------------------------------------
# BUILD METADATA CARD  (high-signal chunk for retrieval)
# ---------------------------------------------------------
def _metadata_card(bid: dict) -> str:
    """
    Compact structured block — always chunk[0].
    Supports both GeM scraper field names and tender pipeline field names.
    """
    department  = bid.get("department") or bid.get("authority", "")
    product_t   = bid.get("product_type") or bid.get("product_name") or bid.get("category", "")
    bid_type    = bid.get("bid_type") or bid.get("tender_type", "")
    status      = bid.get("status") or bid.get("tender_status", "")
    sector      = bid.get("sector", "")
    state       = bid.get("state", "")
    city        = bid.get("city", "")
    summary     = bid.get("tender_summary") or bid.get("work_desc", "")
    proc_type   = bid.get("procurement_type", "")
    competition = bid.get("competition_type", "")

    if summary and len(summary) > 300:
        summary = summary[:300]

    return (
        f"Bid Number: {bid.get('bid_no', '') or bid.get('tender_no', '')}. "
        f"RA Number: {bid.get('ra_no', '')}. "
        f"Status: {status}. "
        f"Bid Type: {bid_type}. "
        f"Procurement Type: {proc_type}. "
        f"Competition: {competition}. "
        f"Product Type: {product_t}. "
        f"Sector: {sector}. "
        f"Item: {bid.get('full_item_name', '')}. "
        f"Items mentioned: {bid.get('full_item_name', '')}. "
        f"Category: {bid.get('category', '')}. "
        f"Sub Category: {bid.get('sub_category', '')}. "
        f"Quantity: {bid.get('quantity', '')}. "
        f"Department: {department}. "
        f"Authority: {department}. "
        f"State: {state}. "
        f"City: {city}. "
        f"Summary: {summary}. "
        f"Start Date: {bid.get('start_date', '')}. "
        f"End Date: {bid.get('end_date', '') or bid.get('due_date', '')}. "
        f"Estimated Value: {bid.get('estimated_value', '') or bid.get('tender_value', '')}. "
        f"Bid Packet Type: {bid.get('bid_packet_type', '')}."
    ).strip()


# ---------------------------------------------------------
# PUBLIC: BUILD CHUNKS FOR ONE BID
# ---------------------------------------------------------
def build_bid_document(bid: dict) -> str:
    """Single string representation (used by callers that want one string)."""
    header = _metadata_card(bid)
    body   = bid.get("full_pdf_text", "") or ""
    return (header + "\n" + body).strip()


def build_bid_chunks(bid: dict) -> list[str]:
    """
    Produces the list of chunks that go into ChromaDB:
      chunk[0]   = structured metadata card (always present)
      chunk[1..] = sliding windows over the cleaned PDF text
    """
    chunks: list[str] = []
    card = _metadata_card(bid)
    if card:
        chunks.append(card)
    body = bid.get("full_pdf_text", "") or ""
    chunks.extend(chunk_text(body))
    return [c for c in chunks if len(c.strip()) > 20]


# ---------------------------------------------------------
# CHUNK TEXT  (sliding window)
# ---------------------------------------------------------
def chunk_text(text: str) -> list[str]:
    if not text or len(text.strip()) < 10:
        return []
    text   = re.sub(r"\s+", " ", text).strip()
    chunks = []
    start  = 0
    step   = max(1, RAG_CHUNK_SIZE - RAG_CHUNK_OVERLAP)
    while start < len(text):
        chunks.append(text[start: start + RAG_CHUNK_SIZE].strip())
        start += step
    return [c for c in chunks if len(c) > 20]


# ---------------------------------------------------------
# EMBED PASSAGES  (no instruction prefix — used by indexer)
# ---------------------------------------------------------
def embed_texts(texts: list[str]) -> list:
    if not texts:
        return []
    log.info(f"  [embedder] Encoding {len(texts)} texts...")
    model      = _get_model()
    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    log.info(f"  [embedder] Encoding complete")
    return embeddings.tolist()


# ---------------------------------------------------------
# EMBED QUERY  (with BGE prefix when applicable — used by query)
# ---------------------------------------------------------
def embed_query(query: str) -> list[float]:
    model = _get_model()
    q     = (_BGE_QUERY_PROMPT + query) if _is_bge() else query
    vec   = model.encode([q], normalize_embeddings=True)
    return vec[0].tolist()
