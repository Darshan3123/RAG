"""
Two-step fix:
1. For bids where full_item_name is empty but category is not,
   copy category → full_item_name in MongoDB.
2. Re-index all bids that have empty category OR full_item_name
   so ChromaDB metadata cards are correct.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.storage.mongo_client import _bids
from shared.utils.logger import get_logger
from shared.rag.embedder import prewarm_model
from indexer.rag.vector_store import upsert_bid

log = get_logger("reindex_partial")


def run():
    col = _bids()

    # ── Step 1: sync full_item_name from category where it's empty ──
    fixed = 0
    for doc in col.find(
        {"$and": [
            {"$or": [{"full_item_name": ""}, {"full_item_name": {"$exists": False}}]},
            {"category": {"$nin": ["", None]}},
        ]},
        {"_id": 1, "bid_no": 1, "category": 1},
    ):
        col.update_one(
            {"_id": doc["_id"]},
            {"$set": {"full_item_name": doc["category"]}},
        )
        log.info(f"  Synced full_item_name for {doc['bid_no']}: {doc['category'][:60]}")
        fixed += 1
    log.info(f"Step 1: synced full_item_name for {fixed} bids")

    # ── Step 2: re-index bids with empty category or full_item_name ──
    query = {"$or": [
        {"category": ""},
        {"category": {"$exists": False}},
        {"full_item_name": ""},
        {"full_item_name": {"$exists": False}},
    ]}

    bids = list(col.find(query, {"_id": 0}))
    log.info(f"Step 2: {len(bids)} bids still need re-indexing")

    # Also always re-index the SAIL bid specifically (known bad)
    sail = col.find_one({"bid_no": "GEM/2026/B/7423108"}, {"_id": 0})
    if sail and sail not in bids:
        bids.insert(0, sail)
        log.info("Added SAIL proximity warning device bid to re-index list")

    if not bids:
        print("Nothing to re-index.")
        return

    prewarm_model()

    for i, bid in enumerate(bids, 1):
        try:
            bid_no = bid.get("bid_no", "?")
            log.info(
                f"  [{i}/{len(bids)}] {bid_no} | "
                f"cat={bid.get('category','')[:40]} | "
                f"item={bid.get('full_item_name','')[:40]}"
            )
            upsert_bid(bid)
        except Exception as e:
            log.error(f"  Failed {bid.get('bid_no','?')}: {e}")

    log.info(f"Done. Re-indexed {len(bids)} bids.")
    print(f"\n✅  Re-indexed {len(bids)} bids.\n")


if __name__ == "__main__":
    run()
