# =========================================================================
# test_postgres_ingestion.py
# Verification script: Read all 61 tender JSON files in downloads/
# and ingest them into the local PostgreSQL "gem-bridge" database.
# =========================================================================
import glob
import json
import os
import sys
import time
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.postgres_db import PostgresBidDatabase, get_db_cursor

def main():
    print("=" * 70)
    print("GeMBridge PostgreSQL v3.0 Ingestion Verification")
    print("Target DB: gem-bridge (localhost:5432)")
    print("=" * 70)

    db = PostgresBidDatabase()

    json_pattern = str(PROJECT_ROOT / "downloads" / "*" / "*.json")
    all_files = glob.glob(json_pattern)

    # Filter to primary tender JSONs (file name matches folder name)
    primary_files = []
    for f in all_files:
        p = Path(f)
        if p.stem == p.parent.name:
            primary_files.append(f)

    print(f"Discovered {len(primary_files)} primary tender JSON files in downloads/.")
    if not primary_files:
        print("No primary tender JSON files found!")
        return

    success_count = 0
    fail_count = 0
    t0 = time.time()

    for i, file_path in enumerate(primary_files, 1):
        try:
            with open(file_path, "r", encoding="utf-8") as fp:
                data = json.load(fp)

            bid_no = data.get("bid", {}).get("bid_no") or Path(file_path).stem
            db.upsert_bid(data)
            success_count += 1
            print(f"[{i:02d}/{len(primary_files)}] OK: {bid_no}")
        except Exception as e:
            fail_count += 1
            print(f"[{i:02d}/{len(primary_files)}] FAILED: {file_path} -> {e}")

    elapsed = time.time() - t0
    print("\n" + "=" * 70)
    print(f"Ingestion Finished in {elapsed:.2f}s ({elapsed/len(primary_files):.3f}s/bid)")
    print(f"Results: {success_count} Succeeded, {fail_count} Failed out of {len(primary_files)}")
    print("=" * 70)

    # Verification counts from PostgreSQL database
    with get_db_cursor(commit=False) as cur:
        tables = [
            "bids",
            "bid_items",
            "bid_consignees",
            "bid_evaluation_schedules",
            "bid_atc_checklist_items",
            "bid_atc_physical_submissions",
            "bid_hyperlinks",
            "bid_terms",
            "bid_atc_analyses",
            "gem_bid_chunks",
        ]
        print("\nRow counts in PostgreSQL 'gem-bridge':")
        for table in tables:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            cnt = cur.fetchone()[0]
            print(f"  - {table:28s}: {cnt:5d} rows")

if __name__ == "__main__":
    main()
