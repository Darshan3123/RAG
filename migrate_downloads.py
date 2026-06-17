#!/usr/bin/env python3
"""
migrate_downloads.py
────────────────────
Moves existing flat PDFs in downloads/ into bid-type subfolders.

Structure after migration:
  downloads/
    Product_Bid_RAs/        GeM-Bidding-XXXXXXX.pdf
    BOQ_Bids/               ...
    Single_Tender/          ...
    ...

Also updates document_path in MongoDB so existing records still point
to the correct file.

Run from the project root:
    python migrate_downloads.py

Pass --dry-run to preview without moving files or updating DB.
"""
import sys, os, re, shutil, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.storage.mongo_client import _bids
from shared.config.settings import DOWNLOAD_DIR
from shared.utils.logger import get_logger

log = get_logger("migrate.downloads")


def _safe_folder(bid_type_name: str) -> str:
    name = bid_type_name.strip()
    name = re.sub(r"[/\\]", "_", name)
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[^\w\-]", "", name)
    return name or "Other"


def run(dry_run: bool = False):
    col = _bids()

    # Build map: filename → (bid_type, document_path)
    file_map: dict[str, tuple[str, str]] = {}
    for doc in col.find({}, {"_id": 1, "bid_no": 1, "bid_type": 1, "document_path": 1}):
        doc_path = doc.get("document_path", "") or ""
        bid_type = doc.get("bid_type", "") or "Other"
        if not doc_path:
            continue
        fname = os.path.basename(doc_path)
        if fname:
            file_map[fname] = (bid_type, doc["_id"])

    moved  = 0
    skipped = 0
    errors  = 0

    # Process every PDF currently in the flat downloads/ root
    try:
        entries = os.listdir(DOWNLOAD_DIR)
    except FileNotFoundError:
        log.error(f"Downloads dir not found: {DOWNLOAD_DIR}")
        return

    pdfs = [f for f in entries if f.lower().endswith(".pdf")
            and os.path.isfile(os.path.join(DOWNLOAD_DIR, f))]

    log.info(f"PDFs in flat root: {len(pdfs)} | dry_run={dry_run}")

    for fname in pdfs:
        src_path = os.path.join(DOWNLOAD_DIR, fname)

        if fname in file_map:
            bid_type, doc_id = file_map[fname]
        else:
            # Not in DB — put in Other/
            bid_type = "Other"
            doc_id   = None

        folder      = _safe_folder(bid_type)
        dest_dir    = os.path.join(DOWNLOAD_DIR, folder)
        dest_path   = os.path.join(dest_dir, fname)

        if os.path.exists(dest_path):
            log.debug(f"  Already moved: {fname}")
            skipped += 1
            continue

        log.info(f"  {fname}  →  {folder}/")

        if not dry_run:
            os.makedirs(dest_dir, exist_ok=True)
            try:
                shutil.move(src_path, dest_path)
                moved += 1
            except Exception as e:
                log.error(f"  Move failed for {fname}: {e}")
                errors += 1
                continue

            # Update document_path in MongoDB
            if doc_id:
                col.update_one(
                    {"_id": doc_id},
                    {"$set": {"document_path": dest_path}}
                )
        else:
            moved += 1

    action = "Would move" if dry_run else "Moved"
    log.info(f"Done — {action}: {moved} | already in subfolder: {skipped} | errors: {errors}")
    print(f"\n✅  {action}: {moved} | skipped: {skipped} | errors: {errors}\n")

    # Print final folder layout
    print("Folder layout:")
    try:
        for entry in sorted(os.listdir(DOWNLOAD_DIR)):
            full = os.path.join(DOWNLOAD_DIR, entry)
            if os.path.isdir(full):
                count = len([f for f in os.listdir(full) if f.endswith(".pdf")])
                print(f"  {entry}/  ({count} PDFs)")
    except Exception:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Organise downloads/ into bid-type subfolders")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without moving files or touching DB")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
