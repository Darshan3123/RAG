# =========================================================================
# clean_all_data.py
# Clean slate utility: Truncates all 10 PostgreSQL tables, pgvector embeddings,
# and resets Redis deduplication keys so you can start the scraper fresh.
# =========================================================================
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import redis
from config.settings import REDIS_URL
from storage.postgres_db import get_db_cursor

def clean_database():
    print("=" * 65)
    print("🧹 GeMBridge Clean Slate: Wiping PostgreSQL & Redis Data")
    print("=" * 65)

    # 1. Truncate PostgreSQL tables
    print("[1/2] Truncating PostgreSQL 'gem-bridge' master & child tables...")
    with get_db_cursor(commit=True) as cur:
        # Cascades to all child tables:
        # bid_items, bid_consignees, bid_evaluation_schedules,
        # bid_atc_checklist_items, bid_atc_physical_submissions,
        # bid_hyperlinks, bid_terms, bid_atc_analyses, gem_bid_chunks (pgvector)
        cur.execute("TRUNCATE TABLE bids RESTART IDENTITY CASCADE;")

    # Verify counts
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
    with get_db_cursor(commit=False) as cur:
        all_zero = True
        for t in tables:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            cnt = cur.fetchone()[0]
            if cnt != 0:
                all_zero = False
            print(f"  - {t:30s}: {cnt} rows")

    if all_zero:
        print("  -> PostgreSQL: 100% CLEAN (All tables have 0 rows).")
    else:
        print("  -> Warning: Some tables still have remaining rows.")

    # 2. Reset Redis Deduplication Keys
    print("\n[2/2] Flushing Redis Broker & Deduplication Cache...")
    try:
        r = redis.Redis.from_url(REDIS_URL)
        r.flushall()
        print("  -> Redis: FLUSHALL completed. All queues and 'gem:seen:*' keys purged.")
    except Exception as e:
        print(f"  -> Redis flush warning: {e}")

    print("\n" + "=" * 65)
    print("✨ Clean Slate Complete! Ready for a fresh crawl.")
    print("=" * 65)

if __name__ == "__main__":
    clean_database()
