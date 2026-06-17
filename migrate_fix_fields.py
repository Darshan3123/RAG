#!/usr/bin/env python3
"""
migrate_fix_fields.py
─────────────────────
Cleans up data types and empty-string fields in the bids collection.

Changes applied per document:
  1. quantity          string → int  (e.g. "373809" → 373809)
  2. earnest_amount    float → int   (root level only; tender_record keeps $numberDecimal)
  3. estimated_value   "" → None
  4. corrigendum_url   "" → None
  5. doc_cost          "" → None
  6. ra_no             "" → None
  7. bid_packet_type   "" → None

Root-level date strings (start_date / end_date / open_date) are kept as DD-MM-YYYY
strings — changing them would break existing consumers with no benefit.

tender_record.$numberDecimal / $numberLong fields are left untouched — they are
the raw MongoDB/BSON format used by the downstream indexer and should stay as-is.

Run from the project root:
    python migrate_fix_fields.py

Safe to re-run — uses $set only; no data is deleted.
Pass --dry-run to preview changes without writing.
"""
import sys, os, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.storage.mongo_client import _bids
from shared.utils.logger import get_logger

log = get_logger("migrate.fix_fields")

# Fields that should be None instead of empty string
_NULLABLE_STR_FIELDS = [
    "estimated_value",
    "corrigendum_url",
    "doc_cost",
    "ra_no",
    "bid_packet_type",
    "contact_email",
    "contact_phone",
]


def run(dry_run: bool = False):
    col   = _bids()
    total = col.count_documents({})
    log.info(f"Total documents: {total} | dry_run={dry_run}")

    updated = skipped = 0

    for doc in col.find({}, {
        "_id": 1, "bid_no": 1,
        "quantity": 1,
        "earnest_amount": 1,
        **{f: 1 for f in _NULLABLE_STR_FIELDS},
    }):
        patch = {}
        bid_no = doc.get("bid_no", "?")

        # 1. quantity: string → int
        qty = doc.get("quantity")
        if isinstance(qty, str) and qty.strip():
            try:
                clean = qty.replace(",", "").strip()
                patch["quantity"] = int(float(clean))
            except ValueError:
                log.warning(f"  {bid_no}: cannot parse quantity={repr(qty)}")
        elif qty is None:
            patch["quantity"] = None

        # 2. earnest_amount: float → int (root level)
        ea = doc.get("earnest_amount")
        if isinstance(ea, float):
            patch["earnest_amount"] = int(ea)

        # 3-7. Empty string fields → None
        for field in _NULLABLE_STR_FIELDS:
            val = doc.get(field)
            if val == "":
                patch[field] = None

        if not patch:
            skipped += 1
            continue

        log.info(f"  {bid_no}: {list(patch.keys())}")

        if not dry_run:
            col.update_one({"_id": doc["_id"]}, {"$set": patch})
        updated += 1

    action = "Would update" if dry_run else "Updated"
    log.info(f"Done — {action}: {updated} | already clean: {skipped}")
    print(f"\n✅  {action}: {updated} | already clean: {skipped}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fix field types in bids collection")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
