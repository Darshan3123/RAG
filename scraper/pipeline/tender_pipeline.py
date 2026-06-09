# =========================================================
# scraper/pipeline/tender_pipeline.py
# Orchestrates external tender API → parse → MongoDB
# =========================================================
from __future__ import annotations
import sys

from scraper.pipeline.tender_api_client import TenderApiClient, load_from_file
from scraper.pipeline.tender_parser     import parse_api_response
from shared.utils.logger                import get_logger
from shared.config.settings             import MONGO_TENDER_COLL, MONGO_DB_NAME, MONGO_URI

log = get_logger("tender_pipeline")


def _get_tender_collection():
    from pymongo import MongoClient
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db     = client[MONGO_DB_NAME]
    col    = db[MONGO_TENDER_COLL]
    col.create_index("tender_id", unique=True)
    return col


def _upsert_tenders(records: list[dict]) -> tuple[int, int]:
    col       = _get_tender_collection()
    new_count = 0
    from datetime import datetime
    now = datetime.utcnow().isoformat()
    for rec in records:
        tid = rec.get("tender_id", "")
        if not tid:
            continue
        existing = col.find_one({"tender_id": tid}, {"_id": 1})
        if existing:
            col.update_one(
                {"tender_id": tid},
                {"$set": {
                    "status":         rec.get("status", ""),
                    "tender_value":   rec.get("tender_value", ""),
                    "contract_value": rec.get("contract_value", ""),
                    "winner_name":    rec.get("winner_name", ""),
                    "winner_bid":     rec.get("winner_bid", ""),
                    "last_seen":      now,
                }}
            )
        else:
            rec["first_seen"] = now
            rec["last_seen"]  = now
            rec["is_new"]     = True
            col.insert_one(rec)
            new_count += 1
            log.info(f"  NEW TENDER saved: {tid}")
    return len(records), new_count


def run_active(category: str = "", state: str = ""):
    log.info("=" * 60)
    log.info("FETCHING ACTIVE TENDERS")
    log.info("=" * 60)
    client  = TenderApiClient()
    raw     = client.fetch_all_active(category=category, state=state)
    records = parse_api_response(raw)
    total, new_count = _upsert_tenders(records)
    log.info(f"DONE | Fetched: {total} | New: {new_count}")


def run_results(category: str = "", state: str = ""):
    log.info("=" * 60)
    log.info("FETCHING TENDER RESULTS (AOC)")
    log.info("=" * 60)
    client  = TenderApiClient()
    raw     = client.fetch_all_results(category=category, state=state)
    records = parse_api_response(raw)
    total, new_count = _upsert_tenders(records)
    log.info(f"DONE | Fetched: {total} | New: {new_count}")


def run_from_file(filepath: str):
    log.info(f"Loading from file: {filepath}")
    raw     = load_from_file(filepath)
    records = parse_api_response(raw)
    log.info(f"Parsed {len(records)} records")
    for r in records:
        print(f"  tender_id: {r['tender_id']} | {r['authority'][:40]} | {r['status']}")
    total, new_count = _upsert_tenders(records)
    log.info(f"Saved {total} records ({new_count} new)")


def tender_stats():
    col = _get_tender_collection()
    total = col.count_documents({})
    open_ = col.count_documents({"status": "OPEN"})
    aoc   = col.count_documents({"status": "AOC"})
    new_  = col.count_documents({"is_new": True})
    print(f"\n{'='*42}\n  Tender Database — Stats\n{'='*42}")
    print(f"  Total tenders : {total}")
    print(f"  OPEN          : {open_}")
    print(f"  AOC (results) : {aoc}")
    print(f"  New           : {new_}")
    print(f"{'='*42}\n")
