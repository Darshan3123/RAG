# =========================================================
# shared/storage/mongo_client.py
# MongoDB storage — replaces the old SQLite database.py.
#
# KEY DIFFERENCE FROM THE OLD database.py:
#   There is NO inline RAG / vector_store call here.
#   The scraper writes bids as {is_new: true}.
#   The indexer reads {is_new: true} bids separately and
#   embeds them independently on the GPU server.
#   This decouples scraping from embedding completely.
# =========================================================
from __future__ import annotations
import json
from datetime import datetime
from shared.config.settings import (
    MONGO_URI, MONGO_DB_NAME,
    MONGO_BIDS_COLL, MONGO_RUNS_COLL,
)
from shared.utils.logger import get_logger

log = get_logger("mongo_client")

_client = None


def _get_client():
    global _client
    if _client is None:
        from pymongo import MongoClient
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        # Trigger a real connection check
        _client.admin.command("ping")
        log.info(f"MongoDB connected: {MONGO_URI}")
    return _client


def _db():
    return _get_client()[MONGO_DB_NAME]


def _bids():
    col = _db()[MONGO_BIDS_COLL]
    # Ensure indexes exist (idempotent)
    col.create_index("card.bid_pdf_url", unique=True)
    col.create_index("is_new")
    col.create_index("first_seen")
    return col


def _runs():
    return _db()[MONGO_RUNS_COLL]


# ---------------------------------------------------------
# UPSERT
# Insert new bid or update last_seen on existing.
# Returns True if this is a NEW bid.
# Note: no RAG call here — the indexer handles that.
# ---------------------------------------------------------
def upsert(doc: dict) -> bool:
    now = datetime.utcnow().isoformat()
    col = _bids()

    doc_url = doc.get("card", {}).get("bid_pdf_url")
    if not doc_url:
        log.error("Upsert failed: Document has no card.bid_pdf_url")
        return False

    existing = col.find_one({"card.bid_pdf_url": doc_url}, {"_id": 1})
    is_new = existing is None

    if is_new:
        doc["first_seen"] = now
        doc["last_seen"]  = now
        doc["is_new"]     = True
        try:
            col.insert_one(doc)
            log.info(f"  NEW BID saved: {doc.get('bid', {}).get('bid_no', 'unknown')}")
        except Exception as e:
            log.error(f"  Insert failed for {doc.get('bid', {}).get('bid_no')}: {e}")
            return False
    else:
        update_fields = {
            "last_seen": now,
            "is_new": False,
        }
        # Update the entire document on re-scrape but preserve metadata
        for k, v in doc.items():
            if k not in ["_id", "first_seen", "last_seen", "is_new"]:
                update_fields[k] = v
                
        col.update_one(
            {"card.bid_pdf_url": doc_url},
            {"$set": update_fields},
        )

    return is_new


# ---------------------------------------------------------
# GET NEW BIDS  (is_new=True — not yet indexed)
# Called by the indexer to find unembedded bids.
# ---------------------------------------------------------
def get_new_bids() -> list[dict]:
    return list(_bids().find({"is_new": True}, {"_id": 0}).sort("first_seen", -1))


# ---------------------------------------------------------
# MARK BIDS AS INDEXED
# Called by the indexer after successful embedding.
# ---------------------------------------------------------
def mark_bids_indexed(document_urls: list[str]):
    if not document_urls:
        return
    result = _bids().update_many(
        {"card.bid_pdf_url": {"$in": document_urls}},
        {"$set": {"is_new": False}}
    )
    log.info(f"Marked {result.modified_count} bids as indexed")


# ---------------------------------------------------------
# MARK ALL SEEN  (called by scheduler after alerting)
# ---------------------------------------------------------
def mark_all_seen():
    _bids().update_many({}, {"$set": {"is_new": False}})


# ---------------------------------------------------------
# GET ALL BIDS  (for full reindex)
# ---------------------------------------------------------
def get_all(projection: dict | None = None) -> list[dict]:
    proj = projection or {"_id": 0}
    return list(_bids().find({}, proj).sort("first_seen", -1))


# ---------------------------------------------------------
# EXISTS CHECK
# ---------------------------------------------------------
def exists(document_url: str) -> bool:
    return _bids().count_documents({"card.bid_pdf_url": document_url}, limit=1) > 0


# ---------------------------------------------------------
# LOG A SCRAPE RUN
# ---------------------------------------------------------
def log_run(bid_type: str, scraped: int, new_bids: int,
            errors: int, duration: float):
    _runs().insert_one({
        "run_at":       datetime.utcnow().isoformat(),
        "bid_type":     bid_type,
        "scraped":      scraped,
        "new_bids":     new_bids,
        "errors":       errors,
        "duration_sec": duration,
    })


# ---------------------------------------------------------
# EXPORT JSON
# ---------------------------------------------------------
def export_json(path: str):
    bids = get_all()
    output = []
    for b in bids:
        b.pop("full_pdf_text", None)   # always strip raw text — too large
        output.append(b)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    log.info(f"JSON exported: {path} ({len(output)} records)")


# ---------------------------------------------------------
# STATS
# ---------------------------------------------------------
def stats() -> dict:
    col = _bids()
    return {
        "total":        col.count_documents({}),
        "new_this_run": col.count_documents({"is_new": True}),
        "total_runs":   _runs().count_documents({}),
    }
