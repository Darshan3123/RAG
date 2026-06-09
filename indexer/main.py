#!/usr/bin/env python3
# =========================================================
# indexer/main.py — Indexer module entry point
#
# Run from project root:   python indexer/main.py --index-new
# Run from module dir:     cd indexer && python main.py --index-new
#
# python main.py --index-new      # embed only bids with is_new=True
# python main.py --reindex-all    # rebuild entire ChromaDB from scratch
# python main.py --stats          # show vector store + MongoDB stats
# =========================================================
import sys
import os

# Works whether called from root (python indexer/main.py)
# or from inside the module dir (cd indexer && python main.py)
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from shared.utils.logger import get_logger
log = get_logger("indexer")


def index_new_bids():
    """
    Read all bids with is_new=True from MongoDB,
    embed them and store in ChromaDB,
    then mark them as indexed (is_new=False).
    """
    from shared.storage import mongo_client as db
    from indexer.rag.vector_store import upsert_bid

    new_bids = db.get_new_bids()
    if not new_bids:
        log.info("No new bids to index.")
        return

    log.info(f"Found {len(new_bids)} new bids to index.")

    # Pre-warm the embedding model once before the batch
    from shared.rag.embedder import prewarm_model
    prewarm_model()

    indexed_urls = []
    for i, bid in enumerate(new_bids, 1):
        try:
            log.info(f"  [{i}/{len(new_bids)}] Indexing {bid.get('bid_no', 'unknown')}")
            upsert_bid(bid)
            indexed_urls.append(bid["document_url"])
        except Exception as e:
            log.error(f"  Failed to index {bid.get('bid_no', '?')}: {e}")

    # Mark successfully indexed bids
    db.mark_bids_indexed(indexed_urls)
    log.info(f"Done. Indexed {len(indexed_urls)}/{len(new_bids)} bids.")


def reindex_all():
    """
    Pull ALL bids from MongoDB and rebuild ChromaDB from scratch.
    Use this when the vector store is out of sync or after
    changing the embedding model.
    """
    from shared.storage import mongo_client as db
    from indexer.rag.vector_store import reindex_all as vs_reindex

    # Exclude full_pdf_text from the projection to reduce memory,
    # then re-fetch it per bid if needed (kept here for simplicity)
    bids = db.get_all(projection={"_id": 0})
    log.info(f"Reindexing {len(bids)} bids from MongoDB...")

    from shared.rag.embedder import prewarm_model
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
  python main.py --index-new     # embed new bids from MongoDB into ChromaDB
  python main.py --reindex-all   # rebuild entire ChromaDB from scratch
  python main.py --stats         # show MongoDB + ChromaDB stats
            """)

    except KeyboardInterrupt:
        print("\n")
        log.info("Interrupted by user.")
        sys.exit(130)
