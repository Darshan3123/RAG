# =========================================================================
# tasks/tier2_document.py
# Tier 2 Worker: Selective Slicing, Document OCR & Relational Ingestion
# Route: document_queue
# =========================================================================
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from tasks.celery_app import app
from config.settings import (
    DOWNLOAD_DIR,
    ENABLE_PDF_ATC_SPLIT,
    OCR_PROVIDER,
)
from core.ocr import DocumentOCRFactory
from core.ocr.pricing import calculate_saved_cost
from core.pdf_splitter import (
    create_core_pdf_for_ocr,
    detect_atc_boundary,
    extract_atc_markdown_pymupdf,
    stitch_hybrid_markdown,
)
from core.parser import parse_bid_data
from core.normalizer import normalize_bid_data, validate_bid_data
from storage.postgres_db import PostgresBidDatabase
from utils.logger import get_logger
from utils.pdf_hyperlinks import inject_hyperlinks_into_markdown

log = get_logger("tier2_document")


@app.task(name="tasks.tier2_document.process_document", bind=True, max_retries=2)
def process_document(
    self,
    safe_bid_no: str,
    card_data: Dict[str, Any],
    pdf_path: str,
    bid_hyperlinks: List[Dict[str, Any]],
    card_html: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Tier 2 Worker Task:
    1. Executes PyMuPDF selective front-page slicing.
    2. Runs Mistral / Cloud OCR on core pages.
    3. Stitches ATC text & injects hyperlinks into Markdown.
    4. Parses 17-section GFR tender schema and normalizes data.
    5. Ingests master and child records into PostgreSQL "gem-bridge".
    6. Dispatches Tier 3 task (tasks.tier3_atc_rag.process_atc_and_embed) to atc_rag_queue.
    """
    log.info(f"[Tier 2] Starting document processing for: {safe_bid_no}")
    bid_dir = os.path.join(DOWNLOAD_DIR, safe_bid_no)
    os.makedirs(bid_dir, exist_ok=True)

    # 0. Ensure PDF exists locally; if missing, retrieve from MinIO S3
    if not os.path.exists(pdf_path):
        s3_key = f"bids/{safe_bid_no}/bid.pdf"
        try:
            from utils.s3_storage import object_exists, download_file
            if object_exists(s3_key):
                local_pdf = os.path.join(bid_dir, f"{safe_bid_no}.pdf")
                download_file(s3_key, local_pdf)
                pdf_path = local_pdf
                log.info(f"[Tier 2] Restored PDF from MinIO: {s3_key} -> {local_pdf}")
        except Exception as s3_fetch_err:
            log.warning(f"[Tier 2] Could not fetch PDF from MinIO: {s3_fetch_err}")

    # 1. Selective PDF Slicing
    split_info = None
    target_ocr_pdf = pdf_path
    if ENABLE_PDF_ATC_SPLIT and os.path.exists(pdf_path):
        try:
            split_info = detect_atc_boundary(pdf_path)
            if split_info and split_info.pages_saved > 0:
                sliced_pdf_path = os.path.join(bid_dir, f"{safe_bid_no}_core.pdf")
                target_ocr_pdf = create_core_pdf_for_ocr(
                    pdf_path=pdf_path,
                    pages_for_ocr=split_info.pages_for_ocr,
                    output_path=sliced_pdf_path,
                )
                log.info(
                    f"[Tier 2] Selective PDF Slicing for {safe_bid_no}: "
                    f"OCR {split_info.pages_for_ocr}/{split_info.total_pages} pages "
                    f"(Saved {split_info.pages_saved} pages via PyMuPDF)"
                )
        except Exception as e:
            log.warning(f"[Tier 2] Selective slicing check failed for {safe_bid_no}: {e}")
            split_info = None
            target_ocr_pdf = pdf_path

    # 2. Document OCR Conversion
    pdf_text = ""
    ocr_usage_data = {}
    try:
        ocr_provider = DocumentOCRFactory.get_provider(OCR_PROVIDER)
        ocr_result = ocr_provider.convert_pdf_to_markdown(
            pdf_path=target_ocr_pdf,
            save_json=True,
            output_dir=bid_dir,
        )
        pdf_text = ocr_result.markdown
        ocr_usage_data = ocr_result.usage.to_dict()

        if split_info and split_info.pages_saved > 0:
            savings = calculate_saved_cost(
                provider=ocr_result.provider,
                model=ocr_result.model,
                pages_saved=split_info.pages_saved,
            )
            ocr_usage_data["total_pdf_pages"] = split_info.total_pages
            ocr_usage_data["pages_for_ocr"] = split_info.pages_for_ocr
            ocr_usage_data["pages_saved_by_slicing"] = split_info.pages_saved
            ocr_usage_data["estimated_savings_usd"] = savings["saved_usd"]
            ocr_usage_data["estimated_savings_inr"] = savings["saved_inr"]

        log.info(
            f"[Tier 2] OCR [{ocr_result.provider.upper()}] complete for {safe_bid_no}: "
            f"{ocr_result.usage.pages_processed} pages, {ocr_result.usage.latency_seconds:.1f}s, "
            f"Cost: ${ocr_result.usage.estimated_cost_usd:.4f} (₹{ocr_result.usage.estimated_cost_inr:.2f})"
        )
    except Exception as e:
        log.error(f"[Tier 2] Document OCR failed for {safe_bid_no}: {e}")

    # 2b. High-Speed PyMuPDF Fallback if OCR returned empty or failed
    if not pdf_text.strip() and os.path.exists(pdf_path):
        try:
            import pymupdf as fitz
            doc = fitz.open(pdf_path)
            pdf_text = "\n".join([page.get_text() for page in doc])
            doc.close()
            log.info(f"[Tier 2] PyMuPDF fallback extracted {len(pdf_text)} characters for {safe_bid_no}")
        except Exception as fitz_err:
            log.error(f"[Tier 2] PyMuPDF text fallback error: {fitz_err}")

    # 3. Stitch PyMuPDF ATC markdown if sliced
    if split_info and split_info.pages_saved > 0 and pdf_text:
        try:
            atc_pymupdf_md = extract_atc_markdown_pymupdf(
                pdf_path=pdf_path,
                split_page_index=split_info.split_page_index,
                heading_y0=split_info.heading_y0,
            )
            pdf_text = stitch_hybrid_markdown(pdf_text, atc_pymupdf_md)
            log.info(f"[Tier 2] Stitched PyMuPDF ATC markdown into {safe_bid_no} ({len(atc_pymupdf_md)} chars)")
        except Exception as e:
            log.warning(f"[Tier 2] Error stitching PyMuPDF ATC text for {safe_bid_no}: {e}")

    # 4. Inject Hyperlinks into Markdown
    if pdf_text and bid_hyperlinks:
        pdf_text = inject_hyperlinks_into_markdown(pdf_text, bid_hyperlinks)

    # 5. Parse Markdown into Structured Schema
    product_type = card_data.get("bid", {}).get("product_type", "PRODUCT")
    parsed_pdf_data = {}
    if pdf_text.strip():
        parsed_pdf_data = parse_bid_data(pdf_text, product_type)
        card_data["bid"]["process_kind"] = parsed_pdf_data.pop("process_kind", "")
        card_data["bid"]["base_type"] = parsed_pdf_data.pop("base_type", "")

        pdf_depts = parsed_pdf_data.get("departments", {})
        if any(pdf_depts.values()):
            card_data["card"]["departments"] = [{
                "ministry_state_name": pdf_depts.get("ministry_state_name", ""),
                "department_name": pdf_depts.get("department_name", ""),
                "organisation_name": pdf_depts.get("organisation_name", ""),
                "office_name": pdf_depts.get("office_name", ""),
            }]

        pdf_items = parsed_pdf_data.get("items", {})
        detailed_items = []
        if pdf_items and isinstance(pdf_items, dict):
            for k, v in pdf_items.items():
                if re.match(r"^item \d+$", k, re.IGNORECASE) and isinstance(v, dict):
                    cat = v.get("item_category", "").strip()
                    q = v.get("quantity")
                    if cat:
                        detailed_items.append({"name": cat, "quantity": q if q is not None else 0})
        if detailed_items:
            card_data["card"]["items"] = detailed_items

        # Save Markdown File
        pdf_md_path = os.path.join(bid_dir, f"{safe_bid_no}.md")
        try:
            with open(pdf_md_path, "w", encoding="utf-8-sig") as f:
                f.write(pdf_text)
        except Exception as e:
            log.warning(f"Could not save Markdown for {safe_bid_no}: {e}")

    # 6. Normalize & Validate
    normalized_data = normalize_bid_data(card_data, parsed_pdf_data, pdf_text)
    validation_data = validate_bid_data(
        bid_no=safe_bid_no,
        card_data=card_data,
        parsed_pdf_data=parsed_pdf_data,
        normalized=normalized_data,
        pdf_path=pdf_path,
    )

    # 7. Assemble Unified Record
    final_bid = {
        "_id": safe_bid_no,
        "bid": card_data.get("bid", {}),
        "card": card_data.get("card", {}),
        "pdf": parsed_pdf_data,
        "hyperlinks": bid_hyperlinks,
        "normalized": normalized_data,
        "validation": validation_data,
        "atc_analysis": {},
        "telemetry": {"ocr": ocr_usage_data},
        "full_pdf_text": pdf_text,
    }

    # Save local JSON file
    final_json_path = os.path.join(bid_dir, f"{safe_bid_no}.json")
    try:
        with open(final_json_path, "w", encoding="utf-8") as f:
            json.dump(final_bid, f, ensure_ascii=False, indent=4, default=str)
    except Exception as e:
        log.warning(f"Could not save JSON artifact for {safe_bid_no}: {e}")

    # 8. PostgreSQL ACID Upsert
    try:
        db = PostgresBidDatabase()
        db.upsert_bid(final_bid)
        log.info(f"[Tier 2] Tender {safe_bid_no} successfully saved to PostgreSQL database.")
    except Exception as db_err:
        log.error(f"[Tier 2] PostgreSQL upsert failed for {safe_bid_no}: {db_err}", exc_info=True)

    # 9. Upload Markdown & Metadata to MinIO S3
    try:
        from utils.s3_storage import upload_bytes as s3_upload_bytes
        if pdf_text:
            s3_upload_bytes(f"bids/{safe_bid_no}/document.md", pdf_text.encode("utf-8"), content_type="text/markdown")
        s3_upload_bytes(f"bids/{safe_bid_no}/metadata.json", json.dumps(final_bid, default=str).encode("utf-8"), content_type="application/json")
        log.info(f"[Tier 2] Streamed document.md and metadata.json to MinIO for {safe_bid_no}")
    except Exception as s3_err:
        log.warning(f"[Tier 2] MinIO upload failed for {safe_bid_no}: {s3_err}")

    # 10. Dispatch to Tier 3 (atc_rag_queue)
    from tasks.tier3_atc_rag import process_atc_and_embed

    process_atc_and_embed.delay(
        safe_bid_no=safe_bid_no,
        pdf_text=pdf_text,
        bid_hyperlinks=bid_hyperlinks,
        parsed_pdf_data=parsed_pdf_data,
    )
    log.info(f"[Tier 2] Dispatched tender {safe_bid_no} to Tier 3 (atc_rag_queue)")

    return {"status": "success", "bid_no": safe_bid_no, "pages": ocr_usage_data.get("pages_processed", 0)}
