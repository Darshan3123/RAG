#!/usr/bin/env python3
# =========================================================
# main.py — Entry point
#
# python main.py                        # continuous hourly loop
# python main.py --once                 # single scrape run
# python main.py --stats                # DB + vector store stats
# python main.py --ask "question"       # single RAG query
# python main.py --ask "q" --filter product_type=Product
# python main.py --chat                 # interactive chat
# python main.py --reindex              # rebuild vector store
# =========================================================
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from utils.logger import get_logger
log = get_logger("main")


def print_stats():
    from storage.database import BidDatabase
    from rag.vector_store import stats as vs_stats
    db = BidDatabase()
    s  = db.stats()
    vs = vs_stats()
    print("\n" + "=" * 42)
    print("  GeM Bid Scraper — Stats")
    print("=" * 42)
    print(f"  SQLite total bids  : {s['total']}")
    print(f"  New (unseen)       : {s['new_this_run']}")
    print(f"  Total runs logged  : {s['total_runs']}")
    print(f"  Vector store chunks: {vs['total_chunks']}")
    print(f"  ChromaDB path      : {vs['chroma_dir']}")
    print("=" * 42 + "\n")


def _print_answer(result: dict):
    print("\n" + "─" * 62)
    print(result["answer"])
    print(f"\n── Sources ({len(result['sources'])} unique bids) ──")
    for s in result["sources"]:
        print(
            f"  [{s['bid_no']}]  "
            f"{s['department'][:40]}  "
            f"Score: {s['relevance_score']:.2%}"
        )
    print("─" * 62 + "\n")


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
    _print_answer(result)


def run_chat():
    from rag.query_engine import QueryEngine, is_exit
    engine = QueryEngine()

    print("\n" + "=" * 62)
    print("  GeM Bid RAG Chat")
    print("  Commands:")
    print("    <question>               — search + LLM answer")
    print("    f:<key>=<value> <q>      — with metadata filter")
    print("    /search <question>       — retrieval only, no LLM")
    print("    quit / bye               — exit")
    print("=" * 62 + "\n")

    while True:
        try:
            raw = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        # ── FIX: check exit BEFORE any processing ──
        if not raw or is_exit(raw):
            print("Bye.")
            break

        # ── /search — retrieval only, no LLM ──
        if raw.lower().startswith("/search "):
            q       = raw[8:].strip()
            results = engine.search_only(q)
            print(f"\n{len(results)} unique bids:\n")
            for r in results:
                # FIX: show full_item_name not chunk text
                item = r.get("full_item_name", "N/A")[:40]
                print(
                    f"  • {r['bid_no']:30s} "
                    f"| {item:40s} "
                    f"| End: {r.get('end_date','N/A'):19s} "
                    f"| {r['score']:.2%}"
                )
            print()
            continue

        # ── optional filter prefix f:key=value ──
        filters  = None
        question = raw
        if raw.startswith("f:"):
            parts = raw.split(" ", 1)
            if len(parts) == 2:
                kv      = parts[0][2:].split("=", 1)
                question = parts[1].strip()
                if len(kv) == 2:
                    filters = {kv[0]: kv[1]}

        result = engine.ask(question, filters=filters)
        _print_answer(result)


def run_reindex():
    from storage.database import BidDatabase
    from rag.vector_store import reindex_all
    db = BidDatabase()
    reindex_all(db)
    print("\nRe-index complete. Run --stats to verify.\n")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--stats" in args:
        print_stats()

    elif "--reindex" in args:
        log.info("Mode: full vector store re-index")
        run_reindex()

    elif "--ask" in args:
        idx      = args.index("--ask")
        question = args[idx + 1] if idx + 1 < len(args) else ""
        filter_str = None
        if "--filter" in args:
            fi         = args.index("--filter")
            filter_str = args[fi + 1] if fi + 1 < len(args) else None
        if question:
            run_ask(question, filter_str)
        else:
            print('Usage: python main.py --ask "your question"')

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