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
# BUILD FACTS TEXT (high-signal dense chunk for retrieval)
# ---------------------------------------------------------
def build_facts_text(bid_doc: dict) -> str:
    """
    Generates a dense summary string from the nested JSON schema.
    This serves as chunk[0] and drives retrieval.
    """
    b = bid_doc.get("bid", {})
    card = bid_doc.get("card", {})
    pdf = bid_doc.get("pdf", {})
    
    pdf_items = pdf.get("items") or []
    card_items = card.get("items") or []
    
    item = pdf_items[0] if pdf_items else {}
    card_item = card_items[0] if card_items else {}
    
    depts = pdf.get("departments") or []
    dept = depts[0] if depts else {}
    
    consignees = pdf.get("consignees") or []
    cons = consignees[0] if consignees else {}

    parts = []

    item_name = item.get('item_category') or card_item.get('name') or 'unknown item'
    qty = item.get('quantity') or card_item.get('quantity') or 'unknown'
    
    parts.append(
        f"This is a {b.get('product_type', 'Bid')} bid "
        f"(base_type={b.get('base_type', '')}) "
        f"for {item_name}, total quantity {qty}."
    )

    if dept:
        parts.append(
            f"It is issued by {dept.get('department_name', '')} in {dept.get('ministry_state_name', '')}."
        )

    t = pdf.get("timing", {})
    parts.append(
        f"Bid submission on the portal runs from {card.get('start_datetime', '')} to {card.get('end_datetime', '')}, "
        f"the Bid End Date/Time in the bid document is {t.get('bid_end_datetime', '')} "
        f"and bids will be opened at {t.get('bid_opening_datetime', '')}. "
        f"Bid offer validity is {t.get('bid_offer_validity_days', '')} days from the Bid End Date."
    )

    ra = pdf.get("ra", {})
    ae = ra.get("auto_extension", {})
    parts.append(
        f"Bid to RA is {'enabled' if ra.get('bid_to_ra_enabled') else 'not enabled'}, "
        f"RA qualification rule = {ra.get('ra_qualification_rule') or 'not specified'}. "
        f"RA runs from {ra.get('ra_start_datetime') or 'unknown'} to {ra.get('ra_end_datetime') or 'unknown'}. "
        f"Auto extension is {'enabled' if ae.get('enabled') else 'disabled'} with a {ae.get('window_minutes') or 15} minute window. "
        f"MSE exemption for RA experience/turnover is {'enabled' if ra.get('mse_relaxation_experience_turnover') else 'disabled'}. "
        f"Startup exemption for RA experience/turnover is {'enabled' if ra.get('startup_relaxation_experience_turnover') else 'disabled'}."
    )

    eval_ = pdf.get("evaluation", {})
    bid_type = pdf.get("bid_type", {})
    parts.append(
        f"Evaluation method is {eval_.get('evaluation_method', '')}, "
        f"type of bid is {bid_type.get('type_of_bid', '')}, "
        f"time allowed for technical clarifications is {bid_type.get('technical_clarification_window_days', '')} days."
    )

    req_docs = pdf.get("documents", {}).get("required_from_seller", [])
    if req_docs:
        parts.append("Documents required from seller include " + ", ".join(req_docs) + ".")

    if cons:
        parts.append(
            f"Consignees include {cons.get('consignee_name', '')} at {cons.get('address_raw', '')}, "
            f"with quantity {cons.get('quantity', '')} and {cons.get('delivery_days', '')} delivery days."
        )

    mii = pdf.get("mii", {})
    mse = pdf.get("mse", {})
    parts.append(
        f"MII purchase preference is {'Yes' if mii.get('mii_purchase_preference') else 'No'}, "
        f"price band {mii.get('mii_price_band_percent', '')}% and max quantity {mii.get('mii_max_quantity_percent', '')}%. "
        f"MSE purchase preference is {'Yes' if mse.get('mse_purchase_preference') else 'No'}, "
        f"price band {mse.get('mse_price_band_percent', '')}% and max quantity {mse.get('mse_max_quantity_percent', '')}%."
    )

    return " ".join(parts).replace("  ", " ")


# ---------------------------------------------------------
# PUBLIC: BUILD CHUNKS FOR ONE BID
# ---------------------------------------------------------
def build_bid_document(bid_doc: dict) -> str:
    """Single string representation (used by callers that want one string)."""
    header = build_facts_text(bid_doc)
    body   = bid_doc.get("full_pdf_text", "") or ""
    return (header + "\n" + body).strip()


def build_bid_chunks(bid_doc: dict) -> list[str]:
    """
    Produces the list of chunks that go into ChromaDB:
      chunk[0]   = structured facts_text (always present)
      chunk[1..] = sliding windows over the cleaned PDF text
    """
    chunks: list[str] = []
    
    # 1) Facts text
    facts = build_facts_text(bid_doc)
    if facts:
        chunks.append(facts)
        
    # 2) Full PDF text
    body = bid_doc.get("full_pdf_text", "") or ""
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
