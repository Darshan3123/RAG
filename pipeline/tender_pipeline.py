# =========================================================
# pipeline/tender_pipeline.py
# Orchestrates the full API → parse → store pipeline
# Called via main.py or directly:
#   python -m pipeline.tender_pipeline --active
#   python -m pipeline.tender_pipeline --results
#   python -m pipeline.tender_pipeline --file <path>
#   python -m pipeline.tender_pipeline --stats
# =========================================================
from __future__ import annotations
import sys
import os

from pipeline.tender_api_client import TenderApiClient, load_from_file
from pipeline.tender_parser     import parse_api_response
from storage.tender_database    import TenderDatabase
from utils.logger               import get_logger

log = get_logger("tender_pipeline")


def run_active(category: str = "", state: str = ""):
    log.info("=" * 60)
    log.info("FETCHING ACTIVE TENDERS")
    log.info("=" * 60)
    client = TenderApiClient()
    db     = TenderDatabase()

    raw     = client.fetch_all_active(category=category, state=state)
    records = parse_api_response(raw)
    total, new_count = db.upsert_many(records)
    db.log_run(total, new_count, source="active_tenders_api")
    db.export_json()

    log.info(f"DONE | Fetched: {total} | New: {new_count}")
    _print_stats(db)


def run_results(category: str = "", state: str = ""):
    log.info("=" * 60)
    log.info("FETCHING TENDER RESULTS (AOC)")
    log.info("=" * 60)
    client = TenderApiClient()
    db     = TenderDatabase()

    raw     = client.fetch_all_results(category=category, state=state)
    records = parse_api_response(raw)
    total, new_count = db.upsert_many(records)
    db.log_run(total, new_count, source="tender_results_api")
    db.export_json()

    log.info(f"DONE | Fetched: {total} | New: {new_count}")
    _print_stats(db)


def run_from_file(filepath: str):
    """Load and process a local JSON file (for testing)."""
    log.info(f"Loading from file: {filepath}")
    db  = TenderDatabase()
    raw = load_from_file(filepath)
    records = parse_api_response(raw)

    log.info(f"Parsed {len(records)} records")
    for r in records:
        print(f"\n  tender_id   : {r['tender_id']}")
        print(f"  tender_no   : {r['tender_no']}")
        print(f"  authority   : {r['authority']}")
        print(f"  status      : {r['status']}")
        print(f"  product     : {r['product_name']}")
        print(f"  tender_value: {r['tender_value']} INR")
        print(f"  due_date    : {r['due_date']}")
        print(f"  state       : {r['state']}")
        print(f"  platform    : {r['platform']}")
        if r.get('winner_name'):
            print(f"  winner      : {r['winner_name']} @ {r['winner_bid']} INR")
        if r.get('document_urls'):
            print(f"  doc_urls    : {len(r['document_urls'])} URLs")
            for u in r['document_urls'][:2]:
                print(f"    → {u[:80]}")

    total, new_count = db.upsert_many(records)
    db.log_run(total, new_count, source=f"file:{filepath}")
    db.export_json()
    log.info(f"Saved {total} records ({new_count} new)")
    _print_stats(db)


def _print_stats(db: TenderDatabase):
    s = db.stats()
    print("\n" + "=" * 42)
    print("  Tender Database — Stats")
    print("=" * 42)
    print(f"  Total tenders : {s['total']}")
    print(f"  OPEN          : {s['open']}")
    print(f"  AOC (results) : {s['aoc']}")
    print(f"  New this run  : {s['new']}")
    print(f"  Total runs    : {s['runs']}")
    print("=" * 42 + "\n")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--stats" in args:
        _print_stats(TenderDatabase())

    elif "--file" in args:
        idx = args.index("--file")
        fp  = args[idx + 1] if idx + 1 < len(args) else ""
        if fp:
            run_from_file(fp)
        else:
            print("Usage: python -m pipeline.tender_pipeline --file path/to/file.json")

    elif "--active" in args:
        cat   = args[args.index("--category") + 1] if "--category" in args else ""
        state = args[args.index("--state") + 1]    if "--state"    in args else ""
        run_active(category=cat, state=state)

    elif "--results" in args:
        cat   = args[args.index("--category") + 1] if "--category" in args else ""
        state = args[args.index("--state") + 1]    if "--state"    in args else ""
        run_results(category=cat, state=state)

    else:
        print("""
Usage:
  python -m pipeline.tender_pipeline --file active_tenders.json   # test with local file
  python -m pipeline.tender_pipeline --file tender_result.json    # test with local file
  python -m pipeline.tender_pipeline --active                     # fetch from API
  python -m pipeline.tender_pipeline --results                    # fetch results from API
  python -m pipeline.tender_pipeline --stats                      # show DB stats
  python -m pipeline.tender_pipeline --active --category "Printing Work" --state Gujarat
        """)
