#!/usr/bin/env python3
"""
migrate_fix_fields.py
─────────────────────
Re-parses key fields from full_pdf_text for all existing MongoDB records
and fixes the 5 data quality issues:

  1. category / authority / search_text — re-extract cleanly (no Hindi noise)
  2. organization_name / office_name    — re-extract with next-line pattern
  3. city / state                       — re-extract with state-name fallback
  4. contact_person                     — re-extract from consignee block
  5. earnest_amount                     — normalize to float
  6. product_name / sector              — re-classify from clean category

Run once from the project root:
    python migrate_fix_fields.py

Safe to re-run — all updates use $set.
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.storage.mongo_client import _bids
from shared.utils.logger import get_logger
from scraper.core.parser import (
    parse_bid_extended,
    classify_sector,
    infer_product_name,
    clean_text,
)

log = get_logger("migrate")


def _to_float(val) -> float:
    import re
    if val is None or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict):
        raw = val.get("$numberDecimal", "0") or "0"
        try:
            return float(re.sub(r"[,\s]", "", str(raw)))
        except ValueError:
            return 0.0
    try:
        return float(re.sub(r"[,\s]", "", str(val)))
    except (ValueError, TypeError):
        return 0.0


def run():
    col = _bids()
    total = col.count_documents({})
    log.info(f"Starting re-parse migration on {total} records...")

    updated = 0
    skipped = 0
    errors  = 0

    for doc in col.find({}, {
        "_id": 1, "bid_no": 1,
        "full_pdf_text": 1,
        "document_path": 1,
        "earnest_amount": 1,
        "tender_record": 1,
    }):
        pdf_text = doc.get("full_pdf_text", "") or ""
        if not pdf_text.strip():
            log.warning(f"  No full_pdf_text for {doc.get('bid_no','?')} — skipping")
            skipped += 1
            continue

        try:
            # Re-parse from the actual PDF file if available (raw text preserves newlines)
            # Fall back to full_pdf_text from DB if file is gone
            doc_path = doc.get("document_path", "")
            if doc_path and os.path.exists(doc_path):
                from scraper.core.parser import extract_pdf_text
                raw_text = extract_pdf_text(doc_path)
            else:
                # full_pdf_text was stored after clean_text() — newlines collapsed.
                # Reconstruct approximate newlines by splitting on Hindi label boundaries.
                raw_text = pdf_text  # best we can do without the file

            ext = parse_bid_extended(
                raw_text,
                pdf_path=doc_path or "",
            )
        except Exception as e:
            log.error(f"  Re-parse failed for {doc.get('bid_no','?')}: {e}")
            errors += 1
            continue

        # Normalize earnest_amount: re-parsed string → float
        raw_emd = ext.get("earnest_amount", "")
        tr_emd  = (doc.get("tender_record") or {}).get("earnest_amount")
        emd_float = _to_float(raw_emd) if raw_emd else _to_float(tr_emd)

        patch = {
            # Clean category / sub_category / search_text
            "category":          ext.get("category", ""),
            "sub_category":      ext.get("sub_category", ""),
            "search_text":       ext.get("search_text", ""),
            "full_item_name":    ext.get("full_item_name", "") or doc.get("full_item_name", ""),
            # Clean authority
            "authority":         ext.get("authority", ""),
            # Re-classified from clean category
            "product_name":      ext.get("product_name", ""),
            "sector":            ext.get("sector", ""),
            "procurement_type":  ext.get("procurement_type", ""),
            # Structured org fields
            "organization_name": ext.get("organization_name", ""),
            "office_name":       ext.get("office_name", ""),
            # Location
            "city":              ext.get("city", ""),
            "state":             ext.get("state", ""),
            "address":           ext.get("address", ""),
            "address_pin":       ext.get("address_pin", ""),
            # Contact
            "contact_person":    ext.get("contact_person", ""),
            "contact_email":     ext.get("contact_email", ""),
            "contact_phone":     ext.get("contact_phone", ""),
            # Normalized money
            "earnest_amount":    emd_float,
        }

        col.update_one({"_id": doc["_id"]}, {"$set": patch})
        updated += 1
        log.info(
            f"  [{updated}/{total}] {doc.get('bid_no','?')} | "
            f"city={patch['city']} state={patch['state']} "
            f"org={patch['organization_name'][:30]} "
            f"emd={patch['earnest_amount']}"
        )

    log.info(
        f"Migration complete — updated: {updated} | "
        f"skipped (no pdf text): {skipped} | errors: {errors}"
    )
    print(f"\n✅  Migration done: {updated} updated | {skipped} skipped | {errors} errors\n")


if __name__ == "__main__":
    run()
