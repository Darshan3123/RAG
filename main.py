#!/usr/bin/env python3
# =========================================================
# main.py — Main Entry Point for GeM Bid System
# =========================================================
"""
GeM Bid Scraper & RAG System — Main CLI Entry Point.

Provides unified command-line flags for executing continuous hourly scraping loops,
single scrape runs, targeted single bid extraction, database statistics reporting,
ChromaDB vector store re-indexing, resetting databases, and interactive RAG Q&A queries.

CLI Usage Examples:
    python main.py                        # Launch continuous scheduled hourly scrape loop
    python main.py --once                 # Execute a single full scrape run and exit
    python main.py --bid "GEM/2026/B/..." # Search and scrape a specific bid number
    python main.py --reset                # Reset SQLite DB, JSON exports, and ChromaDB vector store
    python main.py --stats                # Display SQLite database & ChromaDB vector store statistics
    python main.py --ask "query text"     # Execute single RAG question query against vector database
    python main.py --ask "q" --filter product_type=Product
    python main.py --chat                 # Launch interactive terminal RAG chat session
    python main.py --reindex              # Re-index all database records into ChromaDB
"""

import sys
import os
import shutil
sys.path.insert(0, os.path.dirname(__file__))

from utils.logger import get_logger
log = get_logger("main")


# ---------------------------------------------------------------------------
# RESET & STATS REPORTING
# ---------------------------------------------------------------------------
def run_reset():
    """
    Delete SQLite database, JSON export, and ChromaDB vector store directory for clean testing.
    """
    from config.settings import DB_PATH, JSON_OUT_PATH, CHROMA_DIR, DOWNLOAD_DIR
    log.info("Resetting databases and vector store...")
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        log.info(f"  Removed: {DB_PATH}")
    if os.path.exists(JSON_OUT_PATH):
        os.remove(JSON_OUT_PATH)
        log.info(f"  Removed: {JSON_OUT_PATH}")
    if os.path.exists(CHROMA_DIR):
        shutil.rmtree(CHROMA_DIR)
        log.info(f"  Removed: {CHROMA_DIR}")
    if os.path.exists("output_md"):
        shutil.rmtree("output_md")
        log.info(f"  Removed: output_md")
    print("\nDatabase reset complete. System ready for fresh scrape testing.\n")


def print_stats():
    """
    Fetch and display summary statistics for SQLite database records,
    new/unseen bid counts, run log counts, ChromaDB chunk totals, and storage paths.
    """
    from storage.database import BidDatabase
    from rag.vector_store import stats as vs_stats
    db = BidDatabase()
    s  = db.stats()
    vs = vs_stats()
    print("\n" + "=" * 42)
    print("  GeM Bid Scraper — System Stats")
    print("=" * 42)
    print(f"  SQLite total bids  : {s['total']}")
    print(f"  New (unseen)       : {s['new_this_run']}")
    print(f"  Total runs logged  : {s['total_runs']}")
    print(f"  Vector store chunks: {vs['total_chunks']}")
    print(f"  ChromaDB path      : {vs['chroma_dir']}")
    print("=" * 42 + "\n")


# ---------------------------------------------------------------------------
# RAG PRINTING & QUERY RUNNERS
# ---------------------------------------------------------------------------
def _print_answer(result: dict):
    """
    Format and print RAG query response answer text and source attribution citations.
    
    Args:
        result (dict): Output dictionary returned by QueryEngine containing 'answer' and 'sources'.
    """
    print("\n" + "─" * 62)
    print(result.get("answer", ""))
    sources = result.get("sources", [])
    print(f"\n── Sources ({len(sources)} unique bids) ──")
    for s in sources:
        print(
            f"  [{s.get('bid_no', 'N/A')}]  "
            f"{s.get('department', '')[:40]}  "
            f"Score: {s.get('relevance_score', 0.0):.2%}"
        )
    print("─" * 62 + "\n")


def run_ask(question: str, filter_str: str | None):
    """
    Execute a single RAG question query against vector store documents and LLM engine.
    
    Args:
        question (str): Natural language query string.
        filter_str (str | None): Optional metadata filter string formatted as 'key=value'.
    """
    from rag.query_engine import QueryEngine
    filters = None
    if filter_str:
        kv = filter_str.split("=", 1)
        if len(kv) == 2:
            filters = {kv[0].strip(): kv[1].strip()}
    engine = QueryEngine()
    result = engine.ask(question, filters=filters)
    print(f"\nQ: {result.get('question', question)}")
    _print_answer(result)


def run_chat():
    """
    Launch interactive command-line chat session supporting vector retrieval queries,
    metadata filters, search-only retrieval commands, and exit signals.
    """
    from rag.query_engine import QueryEngine, is_exit
    engine = QueryEngine()

    print("\n" + "=" * 62)
    print("  GeM Bid RAG Interactive Chat")
    print("  Commands:")
    print("    <question>               — vector retrieval + LLM answer")
    print("    f:<key>=<value> <q>      — metadata filtered search query")
    print("    /search <question>       — vector search retrieval only (no LLM)")
    print("    quit / bye               — exit session")
    print("=" * 62 + "\n")

    while True:
        try:
            raw = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not raw or is_exit(raw):
            print("Bye.")
            break

        if raw.lower().startswith("/search "):
            q       = raw[8:].strip()
            results = engine.search_only(q)
            print(f"\n{len(results)} unique bids matching query:\n")
            for r in results:
                item = r.get("full_item_name", "N/A")[:40]
                print(
                    f"  • {r.get('bid_no', 'N/A'):30s} "
                    f"| {item:40s} "
                    f"| End: {r.get('end_date','N/A'):19s} "
                    f"| {r.get('score', 0.0):.2%}"
                )
            print()
            continue

        filters  = None
        question = raw
        if raw.startswith("f:"):
            rest = raw[2:]
            if "=" in rest:
                key, after_eq = rest.split("=", 1)
                tokens = after_eq.split(" ")
                value_tokens = []
                question_tokens = []
                found_question = False
                for tok in tokens:
                    if found_question:
                        question_tokens.append(tok)
                    elif tok and tok[0].islower():
                        found_question = True
                        question_tokens.append(tok)
                    else:
                        value_tokens.append(tok)
                value    = " ".join(value_tokens).strip()
                question = " ".join(question_tokens).strip()
                if key and value and question:
                    filters = {key.strip(): value}
                else:
                    question = raw
                    filters  = None

        result = engine.ask(question, filters=filters)
        _print_answer(result)


def run_reindex():
    """
    Re-index all database bid records into ChromaDB vector store chunks.
    """
    from storage.database import BidDatabase
    from rag.vector_store import reindex_all
    db = BidDatabase()
    reindex_all(db)
    print("\nVector store re-indexing complete. Run 'python main.py --stats' to verify.\n")


# ---------------------------------------------------------------------------
# MAIN CLI DISPATCHER
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    args = sys.argv[1:]

    try:
        # 1. Reset Databases & Vector Store
        if "--reset" in args:
            run_reset()

        # 2. Print Database & Vector Store Statistics
        elif "--stats" in args:
            print_stats()

        # 3. Re-index Vector Database
        elif "--reindex" in args:
            log.info("Mode: full vector store re-index")
            run_reindex()

        # 4. Scrape Specific Single Bid Number
        elif "--bid" in args:
            idx = args.index("--bid")
            bid_no = args[idx + 1] if idx + 1 < len(args) else ""
            if bid_no:
                log.info(f"Mode: scrape single specific bid '{bid_no}'")
                from storage.database import BidDatabase
                from pipeline.scraper import scrape_specific_bid
                db = BidDatabase()
                result = scrape_specific_bid(db, bid_no)
                print(f"\nCompleted specific bid search for: {bid_no}")
                print(f"Result Status: {result.get('status')}\n")
            else:
                print('Usage: python main.py --bid "GEM/2026/B/7768206"')

        # 5. Single RAG Query
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

        # 6. Interactive Chat Mode
        elif "--chat" in args:
            run_chat()

        # 7. Single Scrape Run
        elif "--once" in args:
            log.info("Mode: single scrape run")
            from pipeline.scheduler import start_scheduler
            start_scheduler(run_once=True)

        # 8. Continuous Scheduled Hourly Scrape Loop (Default)
        else:
            log.info("Mode: continuous hourly loop")
            from pipeline.scheduler import start_scheduler
            start_scheduler(run_once=False)

    except KeyboardInterrupt:
        print("\n")
        log.info("Process interrupted by user (Ctrl+C). Shutting down gracefully...")
        try:
            sys.exit(130)  # Standard Linux exit code for SIGINT
        except SystemExit:
            os._exit(130)