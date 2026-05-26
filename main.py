#!/usr/bin/env python3
# =========================================================
# main.py  —  Entry point
#
# Usage:
#   python main.py                        # continuous hourly loop
#   python main.py --once                 # single scrape run + exit
#   python main.py --stats                # DB + vector store stats
#   python main.py --ask "your question"  # RAG query
#   python main.py --ask "IT bids" --filter product_type=Product
#   python main.py --chat                 # interactive RAG chat
#   python main.py --reindex              # rebuild vector store from DB
# =========================================================
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from utils.logger import get_logger
log = get_logger("main")


# ---------------------------------------------------------
def print_stats():
    from storage.database import BidDatabase
    from rag.vector_store import stats as vs_stats
    db = BidDatabase()
    s  = db.stats()
    vs = vs_stats()
    print("\n=== GeM Bid Scraper — Stats ===")
    print(f"  SQLite total bids  : {s['total']}")
    print(f"  New (unseen)       : {s['new_this_run']}")
    print(f"  Total runs logged  : {s['total_runs']}")
    print(f"  Vector store chunks: {vs['total_chunks']}")
    print(f"  ChromaDB path      : {vs['chroma_dir']}")
    print("=" * 35)


# ---------------------------------------------------------
def run_ask(question: str, filter_str: str | None):
    from rag.query_engine import QueryEngine
    filters = None
    if filter_str:
        kv = filter_str.split("=", 1)
        if len(kv) == 2:
            filters = {kv[0]: kv[1]}

    engine = QueryEngine()
    result = engine.ask(question, filters=filters)

    print(f"\nQ: {result['question']}")
    print("-" * 60)
    print(result["answer"])
    print("\nSources:")
    for s in result["sources"]:
        print(
            f"  • {s['bid_no']} | "
            f"{s['department'][:45]} | "
            f"Score: {s['relevance_score']:.2%}"
        )


# ---------------------------------------------------------
def run_chat():
    from rag.query_engine import QueryEngine
    engine = QueryEngine()
    print("\n=== GeM Bid RAG Chat (type 'quit' to exit) ===\n")
    while True:
        try:
            q = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not q or q.lower() in ("quit", "exit", "q"):
            break
        result = engine.ask(q)
        print(f"\nAssistant:\n{result['answer']}\n")
        for s in result["sources"]:
            print(
                f"  [{s['bid_no']}] "
                f"{s['department'][:40]} — "
                f"{s['relevance_score']:.2%}"
            )
        print()


# ---------------------------------------------------------
def run_reindex():
    from storage.database import BidDatabase
    from rag.vector_store import reindex_all
    db = BidDatabase()
    reindex_all(db)


# ---------------------------------------------------------
if __name__ == "__main__":
    args = sys.argv[1:]

    if "--stats" in args:
        print_stats()

    elif "--reindex" in args:
        log.info("Mode: full vector store re-index")
        run_reindex()

    elif "--ask" in args:
        idx = args.index("--ask")
        question = args[idx + 1] if idx + 1 < len(args) else ""
        filter_str = None
        if "--filter" in args:
            fi = args.index("--filter")
            filter_str = args[fi + 1] if fi + 1 < len(args) else None
        if question:
            run_ask(question, filter_str)
        else:
            print("Usage: python main.py --ask \"your question\"")

    elif "--chat" in args:
        run_chat()

    elif "--once" in args:
        log.info("Mode: single scrape run")
        from pipeline.scheduler import start_scheduler
        start_scheduler(run_once=True)

    else:
        log.info("Mode: continuous hourly loop")
        from pipeline.scheduler import start_scheduler
        start_scheduler(run_once=False)
