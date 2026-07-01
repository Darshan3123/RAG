#!/usr/bin/env python3
# =========================================================
# indexer_main.py  —  Indexer entry point (run from root)
#
# python indexer_main.py --index-new     # embed new bids into ChromaDB
# python indexer_main.py --reindex-all   # rebuild ChromaDB from scratch
# python indexer_main.py --stats         # MongoDB + ChromaDB stats
# =========================================================
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.utils.logger import get_logger
log = get_logger("indexer_main")


def index_new_bids():
    from shared.storage import mongo_client as db
    from indexer.rag.vector_store import upsert_bid
    from shared.rag.embedder import prewarm_model

    new_bids = db.get_new_bids()
    if not new_bids:
        log.info("No new bids to index.")
        return

    log.info(f"Found {len(new_bids)} new bids to index.")
    prewarm_model()

    indexed_urls = []
    for i, bid_doc in enumerate(new_bids, 1):
        try:
            b = bid_doc.get("bid", {})
            card = bid_doc.get("card", {})
            bid_no = b.get("bid_no", "unknown")
            doc_url = card.get("bid_pdf_url", "")
            
            log.info(f"  [{i}/{len(new_bids)}] Indexing {bid_no}")
            upsert_bid(bid_doc)
            if doc_url:
                indexed_urls.append(doc_url)
        except Exception as e:
            log.error(f"  Failed to index {bid_doc.get('bid', {}).get('bid_no', '?')}: {e}")

    db.mark_bids_indexed(indexed_urls)
    log.info(f"Done. Indexed {len(indexed_urls)}/{len(new_bids)} bids.")


def reindex_all():
    from shared.storage import mongo_client as db
    from indexer.rag.vector_store import reindex_all as vs_reindex
    from shared.rag.embedder import prewarm_model

    bids = db.get_all(projection={"_id": 0})
    log.info(f"Reindexing {len(bids)} bids from MongoDB...")
    prewarm_model()
    vs_reindex(bids)
    log.info("Full reindex complete.")


def print_stats():
    from shared.storage import mongo_client as db
    from indexer.rag.vector_store import stats as vs_stats

    s  = db.stats()
    vs = vs_stats()
    print(f"\n{'='*42}\n  Indexer — Stats\n{'='*42}")
    print(f"  MongoDB total bids    : {s['total']}")
    print(f"  Unindexed (is_new)    : {s['new_this_run']}")
    print(f"  ChromaDB chunks       : {vs['total_chunks']}")
    print(f"  ChromaDB collection   : {vs['collection']}")
    print(f"  ChromaDB path         : {vs['chroma_dir']}")
    print(f"{'='*42}\n")


if __name__ == "__main__":
    args = sys.argv[1:]

    try:
        if "--stats" in args:
            print_stats()

        elif "--reindex-all" in args:
            log.info("Mode: full reindex from MongoDB")
            reindex_all()

        elif "--index-new" in args:
            log.info("Mode: index new bids only")
            index_new_bids()

        else:
            print("""
Usage:
  python indexer_main.py --index-new     # embed new bids from MongoDB into ChromaDB
  python indexer_main.py --reindex-all   # rebuild entire ChromaDB from scratch
  python indexer_main.py --stats         # show MongoDB + ChromaDB stats
            """)

    except KeyboardInterrupt:
        print("\n")
        log.info("Interrupted by user.")
        sys.exit(130)
