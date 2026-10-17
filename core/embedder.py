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
from typing import Any, Dict, List, Optional
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
      - chunk[1..] = synthesized ATC terms & compliance checklist (if present)
      - remaining = sliding windows over the cleaned PDF text
    """
    chunks: list[str] = []
    card = _metadata_card(bid)
    if card:
        chunks.append(card)

    atc = bid.get("atc_analysis", "") or ""
    if atc and len(atc.strip()) > 20:
        atc_header = f"ATC Compliance Checklist & Specific Terms for {bid.get('bid_no', '')}:\n{atc}"
        chunks.extend(chunk_text(atc_header))

    body = bid.get("full_pdf_text", "") or ""
    chunks.extend(chunk_text(body))
    return [c for c in chunks if len(c.strip()) > 20]


def build_structured_bid_chunks(
    bid: dict,
    atc_result: Optional[dict] = None,
    pdf_text: Optional[str] = None,
) -> list[dict]:
    """
    Produce domain-structured chunks for PostgreSQL `gem_bid_chunks`:
      1. 'item': High-signal structured metadata card (tender ID, department, items, values, dates).
      2. 'compliance': Structured ATC compliance clauses, required uploads, exemptions, and physical submissions.
      3. 'general_pdf': Sliding window text chunks over the bid document body.

    Returns a list of dicts:
      [
        {
          "chunk_type": "item" | "compliance" | "general_pdf",
          "chunk_text": "...",
          "metadata": {...}
        },
        ...
      ]
    """
    chunks: list[dict] = []

    bid_meta = bid.get("bid", {})
    card = bid.get("card", {})
    pdf = bid.get("pdf", {})
    norm = bid.get("normalized", {})

    bid_no = bid_meta.get("bid_no") or card.get("bid_no") or bid.get("bid_no") or bid.get("_id", "Unknown")
    ra_no = bid_meta.get("ra_no") or card.get("ra_no") or bid.get("ra_no", "N/A")
    bid_type = bid_meta.get("bid_type") or card.get("bid_type") or bid.get("bid_type", "Product Bid/RAs")
    product_type = bid_meta.get("product_type") or card.get("product_type") or bid.get("product_type", "Product")

    # Departments
    card_depts = card.get("departments", [{}])
    card_dept = card_depts[0] if isinstance(card_depts, list) and card_depts else {}
    pdf_dept = pdf.get("departments", {}) if isinstance(pdf.get("departments"), dict) else {}
    ministry = pdf_dept.get("ministry_state_name") or card_dept.get("ministry_state_name") or ""
    dept = pdf_dept.get("department_name") or card_dept.get("department_name") or ""
    org = pdf_dept.get("organisation_name") or card_dept.get("organisation_name") or ""
    office = pdf_dept.get("office_name") or card_dept.get("office_name") or ""

    # Financials & Dates
    norm_fin = norm.get("financials", {}) if isinstance(norm.get("financials"), dict) else {}
    pdf_fin = pdf.get("financials", {}) if isinstance(pdf.get("financials"), dict) else {}
    est_val = norm_fin.get("estimated_value_inr") or pdf_fin.get("estimated_value")
    emd_info = norm_fin.get("emd") or pdf_fin.get("emd") or {}
    emd_req = emd_info.get("required", False) if isinstance(emd_info, dict) else False
    emd_amt = emd_info.get("amount_inr") or emd_info.get("amount_total") if isinstance(emd_info, dict) else None
    emd_bank = emd_info.get("advisory_bank") if isinstance(emd_info, dict) else ""

    norm_dates = norm.get("dates", {}) if isinstance(norm.get("dates"), dict) else {}
    end_date = norm_dates.get("end_date_iso") or card.get("end_datetime") or pdf.get("timing", {}).get("bid_end_datetime") or ""

    # Items
    items_list = []
    pdf_items = pdf.get("items", {}) if isinstance(pdf.get("items"), dict) else {}
    for k, v in pdf_items.items():
        if isinstance(v, dict) and "item_category" in v:
            items_list.append(f"{v.get('item_category')} (Qty: {v.get('quantity')})")
    if not items_list and card.get("items"):
        for it in card.get("items", []):
            if isinstance(it, dict):
                items_list.append(f"{it.get('name')} (Qty: {it.get('quantity')})")

    # Consignees
    consignees_list = []
    for c in pdf.get("consignees", []):
        off = c.get("consignee_reporting_officer") or ""
        addr = c.get("consignee_address") or ""
        q = c.get("quantity") or ""
        days = c.get("delivery_days") or ""
        consignees_list.append(f"{off}, {addr} (Qty: {q}, {days} Days)")

    # 1. Structure the Item / Metadata chunk
    meta_lines = [
        "GeM Tender Summary & Metadata Card:",
        f"Bid Number: {bid_no}",
        f"RA Number: {ra_no}",
        f"Bid Type: {bid_type} | Product Type: {product_type}",
        f"Ministry/State: {ministry}",
        f"Department: {dept}",
        f"Organisation: {org}",
        f"Office: {office}",
        f"End Date: {end_date}",
        f"Estimated Value: INR {est_val:,.2f}" if est_val else "Estimated Value: Not Disclosed",
        f"EMD Required: {'Yes - INR ' + f'{emd_amt:,.2f}' if emd_amt else 'Yes' if emd_req else 'No'} (Bank: {emd_bank})" if emd_req else "EMD: Not Required",
    ]
    if items_list:
        meta_lines.append("Items / Categories:")
        for it in items_list[:15]:
            meta_lines.append(f"  - {it}")
    if consignees_list:
        meta_lines.append("Consignees / Delivery Locations:")
        for cs in consignees_list[:5]:
            meta_lines.append(f"  - {cs}")

    meta_text = "\n".join(meta_lines).strip()
    if len(meta_text) > 20:
        chunks.append({
            "chunk_type": "item",
            "chunk_text": meta_text,
            "metadata": {
                "source": "metadata_card",
                "bid_no": bid_no,
                "department": dept,
                "organisation": org,
                "estimated_value": est_val,
            }
        })

    # 2. Structure the Compliance Chunks
    atc_data = atc_result or bid.get("atc_analysis") or {}
    checklist_raw = atc_data.get("checklist", {})
    checklist_dict = {}
    if isinstance(checklist_raw, list):
        for item in checklist_raw:
            if isinstance(item, dict):
                checklist_dict.update(item)
    elif isinstance(checklist_raw, dict):
        checklist_dict = checklist_raw

    for cat_name, clauses in checklist_dict.items():
        if cat_name == "PHYSICAL_SUBMISSIONS":
            if isinstance(clauses, list) and clauses:
                phys_lines = [f"GeM Tender {bid_no} - Physical Offline Submissions Required:"]
                for sub in clauses:
                    if isinstance(sub, dict):
                        phys_lines.append(
                            f"- Item: {sub.get('Item') or 'Physical Doc'} | "
                            f"Deadline: {sub.get('Deadline') or 'N/A'} | "
                            f"In Favor Of: {sub.get('In Favor Of') or 'N/A'} | "
                            f"Payable At: {sub.get('Payable At') or 'N/A'} | "
                            f"Address: {sub.get('Delivery Address') or 'N/A'} | "
                            f"Original Clause: {sub.get('Original Text') or ''}"
                        )
                phys_text = "\n".join(phys_lines).strip()
                if len(phys_text) > 30:
                    chunks.append({
                        "chunk_type": "compliance",
                        "chunk_text": phys_text,
                        "metadata": {
                            "source": "atc_compliance",
                            "bid_no": bid_no,
                            "category": "PHYSICAL_SUBMISSIONS",
                        }
                    })
        else:
            if isinstance(clauses, list) and clauses:
                cat_clean = cat_name.replace("_", " ").title()
                cat_lines = [f"GeM Tender {bid_no} - ATC Compliance [{cat_clean}]:"]
                for cl in clauses:
                    if isinstance(cl, str) and cl.strip():
                        cat_lines.append(f"- {cl.strip()}")
                cat_text = "\n".join(cat_lines).strip()
                if len(cat_text) > 30:
                    if len(cat_text) > RAG_CHUNK_SIZE * 2:
                        for idx, sub_chunk in enumerate(chunk_text(cat_text)):
                            chunks.append({
                                "chunk_type": "compliance",
                                "chunk_text": sub_chunk,
                                "metadata": {
                                    "source": "atc_compliance",
                                    "bid_no": bid_no,
                                    "category": cat_name,
                                    "part": idx + 1,
                                }
                            })
                    else:
                        chunks.append({
                            "chunk_type": "compliance",
                            "chunk_text": cat_text,
                            "metadata": {
                                "source": "atc_compliance",
                                "bid_no": bid_no,
                                "category": cat_name,
                            }
                        })

    # Buyer specific generic ATC text
    buyer_atc = (
        pdf.get("terms", {}).get("buyer_atc", {}).get("generic")
        if isinstance(pdf.get("terms"), dict) and isinstance(pdf.get("terms", {}).get("buyer_atc"), dict)
        else ""
    )
    if not buyer_atc:
        buyer_atc = bid.get("buyer_atc_text") or ""
    if buyer_atc and len(buyer_atc.strip()) > 50:
        for idx, sub_chunk in enumerate(chunk_text(buyer_atc)):
            chunks.append({
                "chunk_type": "compliance",
                "chunk_text": f"Buyer Added Terms and Conditions for {bid_no} (Part {idx + 1}):\n{sub_chunk}",
                "metadata": {
                    "source": "buyer_atc_text",
                    "bid_no": bid_no,
                    "part": idx + 1,
                }
            })

    # 3. Structure General PDF Chunks
    raw_pdf_text = pdf_text or bid.get("full_pdf_text") or ""
    if raw_pdf_text and len(raw_pdf_text.strip()) > 50:
        text_windows = chunk_text(raw_pdf_text)
        for idx, win in enumerate(text_windows):
            chunks.append({
                "chunk_type": "general_pdf",
                "chunk_text": win,
                "metadata": {
                    "source": "general_pdf",
                    "bid_no": bid_no,
                    "chunk_index": idx,
                }
            })

    return chunks


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


def generate_bid_embeddings(
    bid_data: dict,
    atc_result: Optional[dict] = None,
    pdf_text: Optional[str] = None,
) -> list[dict]:
    """
    1. Generates domain-structured chunks (item card, compliance clauses, general pdf text).
    2. Computes 768-dim BGE vector embeddings in batched mode.
    3. Returns enriched chunk dictionaries ready for insertion into gem_bid_chunks.
    """
    chunks = build_structured_bid_chunks(bid_data, atc_result=atc_result, pdf_text=pdf_text)
    if not chunks:
        return []

    texts = [c["chunk_text"] for c in chunks]
    embeddings = embed_texts(texts)

    for i, emb in enumerate(embeddings):
        chunks[i]["embedding"] = emb

    return chunks


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
