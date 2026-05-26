# =========================================================
# rag/embedder.py
# Converts bid text into vector embeddings using
# sentence-transformers (runs fully LOCAL, no API key)
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

# Lazy-load — only import when first used
_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        log.info(f"Loading embedding model: {RAG_EMBEDDING_MODEL}")
        _model = SentenceTransformer(RAG_EMBEDDING_MODEL)
        log.info("Embedding model ready")
    return _model


# =========================================================
# CHUNK TEXT
# Splits long PDF text into overlapping windows so each
# chunk fits the embedding model's context window (512 tok)
# =========================================================
def chunk_text(text: str) -> list[str]:
    """
    Splits text into overlapping chunks.
    Returns list of non-empty string chunks.
    """
    if not text or len(text.strip()) < 10:
        return []

    # clean whitespace
    text = re.sub(r"\s+", " ", text).strip()

    chunks = []
    start  = 0
    while start < len(text):
        end = start + RAG_CHUNK_SIZE
        chunks.append(text[start:end].strip())
        start += RAG_CHUNK_SIZE - RAG_CHUNK_OVERLAP

    return [c for c in chunks if len(c) > 20]


# =========================================================
# BUILD DOCUMENT FOR A BID
# Creates a rich text document from all bid metadata
# so the embedder gets structured context, not raw PDF dump
# =========================================================
def build_bid_document(bid: dict) -> str:
    """
    Combines structured fields + PDF text into one
    rich string for embedding. Structured fields are
    repeated at the top so they dominate the embedding.
    """
    header = (
        f"Bid Number: {bid.get('bid_no', '')} "
        f"RA Number: {bid.get('ra_no', '')} "
        f"Bid Type: {bid.get('bid_type', '')} "
        f"Product Type: {bid.get('product_type', '')} "
        f"Item: {bid.get('full_item_name', '')} "
        f"Quantity: {bid.get('quantity', '')} "
        f"Department: {bid.get('department', '')} "
        f"Start Date: {bid.get('start_date', '')} "
        f"End Date: {bid.get('end_date', '')} "
        f"Estimated Value: {bid.get('estimated_value', '')} "
        f"Bid Packet Type: {bid.get('bid_packet_type', '')} "
    )
    pdf_body = bid.get("full_pdf_text", "")
    return (header + " " + pdf_body).strip()


# =========================================================
# EMBED STRINGS
# Returns list of embedding vectors (numpy arrays)
# =========================================================
def embed_texts(texts: list[str]) -> list:
    model = _get_model()
    if not texts:
        return []
    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True,   # cosine similarity ready
    )
    return embeddings.tolist()


# =========================================================
# EMBED A SINGLE QUERY STRING
# =========================================================
def embed_query(query: str) -> list[float]:
    model = _get_model()
    vec = model.encode(
        [query],
        normalize_embeddings=True,
    )
    return vec[0].tolist()
