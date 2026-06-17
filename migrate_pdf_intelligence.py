#!/usr/bin/env python3
"""
migrate_pdf_intelligence.py
───────────────────────────
Backfills the `pdf_intelligence` field on all existing MongoDB tender records
that are missing it (or have an empty dict).

For each record:
  - Uses the PDF file on disk (document_path) if it still exists
  - Falls back to full_pdf_text stored in MongoDB if the file is gone
  - Skips records that have no text at all

Run from the project root:
    python migrate_pdf_intelligence.py

Safe to re-run — only processes docs where pdf_intelligence is missing/empty.
Pass --force to re-process ALL records regardless.
"""
import sys, os, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.storage.mongo_client import _bids
from shared.utils.logger import get_logger
from scraper.core.parser import extract_pdf_text, extract_pdf_intelligence

log = get_logger("migrate.pdf_intelligence")


def run(force: bool = False):
    col = _bids()

    if force:
        query = {}
        log.info("--force mode: processing ALL records")
    else:
        # Only records where pdf_intelligence is absent or empty
        query = {"$or": [
            {"pdf_intelligence": {"$exists": False}},
            {"pdf_intelligence": None},
            {"pdf_intelligence": {}},
        ]}

    total = col.count_documents(query)
    log.info(f"Records to process: {total}")

    if total == 0:
        print("✅  Nothing to migrate — all records already have pdf_intelligence.")
        return

    updated = 0
    skipped = 0
    errors  = 0

    for doc in col.find(query, {
        "_id": 1, "bid_no": 1,
        "full_pdf_text": 1,
        "document_path": 1,
    }):
        bid_no   = doc.get("bid_no", "?")
        doc_path = doc.get("document_path", "") or ""

        # ── Get raw PDF text ────────────────────────────────────────────────
        raw_text = ""
        if doc_path and os.path.exists(doc_path):
            try:
                raw_text = extract_pdf_text(doc_path)
            except Exception as e:
                log.warning(f"  PDF read failed for {bid_no} ({doc_path}): {e} — falling back to DB text")

        if not raw_text.strip():
            raw_text = doc.get("full_pdf_text", "") or ""

        if not raw_text.strip():
            log.warning(f"  No text for {bid_no} — skipping")
            skipped += 1
            continue

        # ── Extract PDF intelligence ────────────────────────────────────────
        try:
            pdf_intel = extract_pdf_intelligence(raw_text)
        except Exception as e:
            log.error(f"  extract_pdf_intelligence failed for {bid_no}: {e}", exc_info=True)
            errors += 1
            continue

        col.update_one({"_id": doc["_id"]}, {"$set": {"pdf_intelligence": pdf_intel}})
        updated += 1

        # Brief summary log
        tl = pdf_intel.get("timeline", {})
        fi = pdf_intel.get("financials", {})
        ci = len(pdf_intel.get("consignee_items", []))
        log.info(
            f"  [{updated}/{total}] {bid_no} | "
            f"opening={tl.get('bid_opening_datetime')} | "
            f"emd={fi.get('emd_amount')} | "
            f"consignees={ci}"
        )

    log.info(
        f"Migration complete — "
        f"updated: {updated} | skipped (no text): {skipped} | errors: {errors}"
    )
    print(f"\n✅  Done: {updated} updated | {skipped} skipped | {errors} errors\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill pdf_intelligence on existing tender records")
    parser.add_argument(
        "--force", action="store_true",
        help="Re-process ALL records, not just missing ones",
    )
    args = parser.parse_args()
    run(force=args.force)
