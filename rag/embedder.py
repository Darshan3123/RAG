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
        import torch
        from sentence_transformers import SentenceTransformer

        device = "cuda" if torch.cuda.is_available() else "cpu"

        # Force fully offline mode — model is already cached locally.
        # This prevents SSL certificate errors on corporate networks
        # where Python can't verify HuggingFace's TLS certificate.
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_DATASETS_OFFLINE"] = "1"
        os.environ["HF_HUB_OFFLINE"] = "1"

        log.info(f"Loading embedding model: {RAG_EMBEDDING_MODEL} on device '{device}' (offline mode)")
        try:
            _model = SentenceTransformer(RAG_EMBEDDING_MODEL, device=device, local_files_only=True)
        except Exception as e:
            log.warning(f"Offline load failed, attempting to download model {RAG_EMBEDDING_MODEL}...")
            os.environ.pop("TRANSFORMERS_OFFLINE", None)
            os.environ.pop("HF_DATASETS_OFFLINE", None)
            os.environ.pop("HF_HUB_OFFLINE", None)
            _model = SentenceTransformer(RAG_EMBEDDING_MODEL, device=device, local_files_only=False)
            
        log.info(f"Embedding model ready on device '{device}'")
    return _model


# =========================================================
# BUILD A HIGH-SIGNAL DOC FOR ONE BID
# =========================================================
def _metadata_card(bid: dict) -> str:
    """Compact, repeat-key block — high signal for retrieval."""
    return (
        f"Bid Number: {bid.get('bid_no', '')}. "
        f"RA Number: {bid.get('ra_no', '')}. "
        f"Bid Type: {bid.get('bid_type', '')}. "
        f"Product Type: {bid.get('product_type', '')}. "
        f"Item: {bid.get('full_item_name', '')}. "
        f"Items mentioned: {bid.get('full_item_name', '')}. "
        f"Quantity: {bid.get('quantity', '')}. "
        f"Department: {bid.get('department', '')}. "
        f"Start Date: {bid.get('start_date', '')}. "
        f"End Date: {bid.get('end_date', '')}. "
        f"Estimated Value: {bid.get('estimated_value', '')}. "
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
    model = _get_model()
    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
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
