# =========================================================
# rag/embedder.py
# Converts bid text into vector embeddings using
# sentence-transformers (runs fully LOCAL, no API key).
#
# IMPROVEMENTS (this revision):
#   1. Default model upgraded to a stronger English encoder
#      (set RAG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5 in .env).
#   2. BGE models require a *query instruction* prefix for
#      retrieval; we add it automatically when the model name
#      contains 'bge'.
#   3. `build_bid_document` now produces a high-signal
#      'metadata card' chunk plus optional PDF body chunks
#      so structured fields dominate retrieval.
# =========================================================
from __future__ import annotations
import re
from config.settings import (
    RAG_EMBEDDING_MODEL,
    RAG_CHUNK_SIZE,
    RAG_CHUNK_OVERLAP,
)
from utils.logger import get_logger

log = get_logger("embedder")

_model = None

# BGE retrieval prompt (recommended by the model authors).
# Only used when the embedding model is a BGE variant.
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

        # Respect HF_OFFLINE env var — set to "true" to block network calls
        offline = os.getenv("HF_OFFLINE", "false").lower() in ("1", "true", "yes")
        if offline:
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            os.environ["HF_DATASETS_OFFLINE"] = "1"
            os.environ["HF_HUB_OFFLINE"] = "1"

        mode = "offline" if offline else "online"
        log.info(f"Loading embedding model: {RAG_EMBEDDING_MODEL} ({mode})")
        log.info("  This may take 60-90 seconds on first load...")
        _model = SentenceTransformer(
            RAG_EMBEDDING_MODEL,
            local_files_only=offline,
        )
        log.info("Embedding model ready")
    return _model


def prewarm_model():
    """
    Pre-warm the embedding model by loading it and doing a test encode.
    Call this at startup to avoid blocking during scraping.
    """
    log.info("Pre-warming embedding model...")
    model = _get_model()
    # Do a test encode to ensure everything is loaded
    test_text = ["Test embedding to warm up the model"]
    model.encode(test_text, show_progress_bar=False)
    log.info("Embedding model pre-warmed and ready")


# =========================================================
# BUILD A HIGH-SIGNAL DOC FOR ONE BID
# =========================================================
def _metadata_card(bid: dict) -> str:
    """Compact, repeat-key block — high signal for retrieval.

    Supports both GeM scraper field names and tender pipeline field names:
      - department   / authority
      - product_type / product_name / category
      - bid_type     / tender_type
      - status       / tender_status
      - sector
      - state / city
      - tender_summary / work_desc
    """
    # Resolve dual field-name conventions
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

    # Truncate long descriptions to avoid bloating the card
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


def build_bid_document(bid: dict) -> str:
    """Used by callers that still want one big string."""
    header = _metadata_card(bid)
    body = bid.get("full_pdf_text", "") or ""
    return (header + "\n" + body).strip()


def build_bid_chunks(bid: dict) -> list[str]:
    """
    Produce the chunks that will actually be indexed:
      - chunk[0] = high-signal metadata card (always present)
      - chunk[1..] = sliding windows over the cleaned PDF text
    """
    chunks: list[str] = []
    card = _metadata_card(bid)
    if card:
        chunks.append(card)

    body = bid.get("full_pdf_text", "") or ""
    chunks.extend(chunk_text(body))
    return [c for c in chunks if len(c.strip()) > 20]


# =========================================================
# CHUNK TEXT
# =========================================================
def chunk_text(text: str) -> list[str]:
    if not text or len(text.strip()) < 10:
        return []
    text = re.sub(r"\s+", " ", text).strip()
    chunks = []
    start = 0
    step = max(1, RAG_CHUNK_SIZE - RAG_CHUNK_OVERLAP)
    while start < len(text):
        end = start + RAG_CHUNK_SIZE
        chunks.append(text[start:end].strip())
        start += step
    return [c for c in chunks if len(c) > 20]


# =========================================================
# EMBED PASSAGES (no instruction prefix)
# =========================================================
def embed_texts(texts: list[str]) -> list:
    if not texts:
        return []
    log.info(f"  [embedder] Encoding {len(texts)} texts...")
    model = _get_model()
    log.info(f"  [embedder] Model loaded, starting encode...")
    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    log.info(f"  [embedder] Encoding complete")
    return embeddings.tolist()


# =========================================================
# EMBED A QUERY (with BGE prefix when applicable)
# =========================================================
def embed_query(query: str) -> list[float]:
    model = _get_model()
    q = query
    if _is_bge():
        q = _BGE_QUERY_PROMPT + query
    vec = model.encode([q], normalize_embeddings=True)
    return vec[0].tolist()
