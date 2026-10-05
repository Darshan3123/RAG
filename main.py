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
    python main.py --reset-all            # Complete purge: DB, ChromaDB, downloads/, and logs/
    python main.py --clear-db             # Delete SQLite DB and JSON export only
    python main.py --clear-chroma         # Delete ChromaDB vector store only
    python main.py --clear-downloads      # Delete all downloaded bid PDFs & folders only
    python main.py --clear-logs           # Delete all log files only
    python main.py --stats                # Display SQLite database & ChromaDB vector store statistics
    python main.py --ask "query text"     # Execute single RAG question query against vector database
    python main.py --ask "q" --filter product_type=Product
    python main.py --chat                 # Launch interactive terminal RAG chat session
    python main.py --reindex              # Re-index all database records into ChromaDB
    python main.py --analyze-atc <path>   # Run ATC compliance extraction on tender or folder
"""

import sys
import os
import shutil

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(__file__))

from utils.logger import get_logger
log = get_logger("main")


# ---------------------------------------------------------------------------
# RESET & STATS REPORTING
# ---------------------------------------------------------------------------
def clear_db():
    """Delete SQLite database and JSON export."""
    from config.settings import DB_PATH, JSON_OUT_PATH
    log.info("Clearing SQLite database and JSON export...")
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        log.info(f"  Removed: {DB_PATH}")
    if os.path.exists(JSON_OUT_PATH):
        os.remove(JSON_OUT_PATH)
        log.info(f"  Removed: {JSON_OUT_PATH}")
    print("\n✅ SQLite database and JSON export cleared successfully.\n")


def clear_chroma():
    """Delete ChromaDB vector store directory."""
    from config.settings import CHROMA_DIR
    log.info("Clearing ChromaDB vector store...")
    if os.path.exists(CHROMA_DIR):
        shutil.rmtree(CHROMA_DIR)
        log.info(f"  Removed: {CHROMA_DIR}")
    print("\n✅ ChromaDB vector store cleared successfully.\n")


def clear_downloads():
    """Delete downloaded bid PDFs and folders."""
    from config.settings import DOWNLOAD_DIR
    log.info("Clearing downloaded files and folders...")
    if os.path.exists(DOWNLOAD_DIR):
        shutil.rmtree(DOWNLOAD_DIR)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        log.info(f"  Cleared: {DOWNLOAD_DIR}")
    print("\n✅ Downloads directory cleared successfully.\n")


def clear_logs():
    """Delete log files."""
    from config.settings import LOG_DIR
    log.info("Clearing logs...")
    if os.path.exists(LOG_DIR):
        shutil.rmtree(LOG_DIR)
        os.makedirs(LOG_DIR, exist_ok=True)
        log.info(f"  Cleared: {LOG_DIR}")
    print("\n✅ Logs directory cleared successfully.\n")


def run_reset(include_downloads: bool = False, include_logs: bool = False):
    """
    Delete SQLite database, JSON export, and ChromaDB vector store directory.
    Optionally also purges downloads and logs.
    """
    from config.settings import DB_PATH, JSON_OUT_PATH, CHROMA_DIR, DOWNLOAD_DIR, LOG_DIR
    log.info("Resetting databases and storage...")
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
    if include_downloads and os.path.exists(DOWNLOAD_DIR):
        shutil.rmtree(DOWNLOAD_DIR)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        log.info(f"  Purged: {DOWNLOAD_DIR}")
    if include_logs and os.path.exists(LOG_DIR):
        shutil.rmtree(LOG_DIR)
        os.makedirs(LOG_DIR, exist_ok=True)
        log.info(f"  Purged: {LOG_DIR}")

    if include_downloads or include_logs:
        print("\n✅ Complete system purge finished (DB, ChromaDB, Downloads, Logs cleared).\n")
    else:
        print("\n✅ Database & ChromaDB reset complete. System ready for fresh scrape testing.\n")


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


def run_analyze_atc(target: str):
    """
    Run ATC compliance analysis on a file, directory, or bid folder.
    """
    from pipeline.atc_analyzer import analyze_bid_atc
    import json
    target_path = os.path.abspath(target)
    
    md_files = []
    if os.path.isfile(target_path) and target_path.endswith(".md"):
        md_files = [target_path]
    elif os.path.isdir(target_path):
        for root, _, files in os.walk(target_path):
            for f in files:
                if f.endswith(".md") and not f.endswith("_ATC.md") and not f.endswith("_INFER_OUTPUT.md"):
                    md_files.append(os.path.join(root, f))
    else:
        # Check if it corresponds to a folder under downloads
        safe_bid = target.replace("/", "_")
        cand = os.path.join("downloads", safe_bid, f"{safe_bid}.md")
        if os.path.exists(cand):
            md_files = [cand]
        else:
            print(f"Target '{target}' not found as a .md file, directory, or downloads folder.")
            return

    if not md_files:
        print(f"No source markdown files found for target '{target}'.")
        return

    print(f"\nRunning ATC compliance analysis on {len(md_files)} file(s)...\n")
    for md_file in md_files:
        base_name = os.path.splitext(os.path.basename(md_file))[0]
        bid_dir = os.path.dirname(md_file)
        
        # Check for companion JSON to pull hyperlinks
        json_file = os.path.join(bid_dir, f"{base_name}.json")
        hyperlinks = []
        if os.path.exists(json_file):
            try:
                with open(json_file, "r", encoding="utf-8") as jf:
                    jdata = json.load(jf)
                    hyperlinks = jdata.get("hyperlinks", [])
            except Exception:
                pass

        try:
            with open(md_file, "r", encoding="utf-8") as mf:
                content = mf.read()
            
            res = analyze_bid_atc(
                bid_no=base_name,
                markdown_text=content,
                hyperlinks=hyperlinks,
                save_dir=bid_dir
            )
            print(f"  [{res.get('status').upper()}] {base_name} ({res.get('elapsed_seconds', 0)}s)")
            chk = res.get("checklist", {})
            std_docs = len(chk.get("standard_documents", []))
            atc_docs = len(chk.get("clarified_atc_documents", []))
            exm_docs = len(chk.get("exemption_documents", []))
            phy_subs = len(chk.get("physical_submissions", []))
            com_trms = len(chk.get("commercial_terms", []))
            print(f"       Std Docs: {std_docs} | Clarified ATC: {atc_docs} | Exemptions: {exm_docs} | Physical: {phy_subs} | Terms: {com_trms}")
        except Exception as e:
            print(f"  [ERROR] {base_name}: {e}")
    print("\nATC analysis batch finished.\n")


# ---------------------------------------------------------------------------
# MAIN CLI DISPATCHER
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    args = sys.argv[1:]

    try:
        # 1. Reset & Clear Operations
        if "--reset-all" in args or "--purge" in args:
            run_reset(include_downloads=True, include_logs=True)
        elif "--reset" in args:
            run_reset()
        elif "--clear-db" in args:
            clear_db()
        elif "--clear-chroma" in args:
            clear_chroma()
        elif "--clear-downloads" in args:
            clear_downloads()
        elif "--clear-logs" in args:
            clear_logs()

        # 2. Print Database & Vector Store Statistics
        elif "--stats" in args:
            print_stats()

        # 3. Re-index Vector Database
        elif "--reindex" in args:
            log.info("Mode: full vector store re-index")
            run_reindex()

        # 4. Analyze ATC Compliance Checklist
        elif "--analyze-atc" in args:
            idx = args.index("--analyze-atc")
            target = args[idx + 1] if idx + 1 < len(args) else ""
            if target:
                run_analyze_atc(target)
            else:
                print('Usage: python main.py --analyze-atc <file_path_or_folder>')

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