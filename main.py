#!/usr/bin/env python3
# =========================================================
# main.py — Entry point
#
# ── GeM Scraper ──────────────────────────────────────────
# python main.py                        # continuous hourly loop
# python main.py --once                 # single scrape run
# python main.py --stats                # DB + vector store stats
# python main.py --ask "question"       # single RAG query
# python main.py --ask "q" --filter product_type=Product
# python main.py --chat                 # interactive chat
# python main.py --reindex              # rebuild vector store
#
# ── Tender API Pipeline ──────────────────────────────────
# python main.py --tender-active                    # fetch open tenders from API
# python main.py --tender-results                   # fetch awarded tenders from API
# python main.py --tender-file active_tenders.json  # load from local file
# python main.py --tender-stats                     # tender DB stats
# python main.py --tender-active --category "Printing Work" --state Gujarat
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
        # Supports values with spaces: f:bid_type=Global Tender my question
        # Strategy: parse f:key=value_token, then the rest is the question.
        # For multi-word filter values, user can use underscore or the value
        # as-is since we consume everything up to the question start heuristic.
        # Better: split f:key=value where value ends at first word that would
        # be a question (we just split the whole token on first space and let
        # key=value include everything before the second space-separated group).
        #
        # Simplest robust approach: f: prefix consumes key=rest_of_first_token,
        # BUT to support "f:bid_type=Global Tender what bids" correctly we
        # require the question to be separated by TWO spaces, or we detect the
        # filter value boundary by checking how many words belong to the value.
        #
        # We use the pragmatic approach: split f:key=value where the value is
        # everything after = in the first token, and remaining tokens are query.
        filters  = None
        question = raw
        if raw.startswith("f:"):
            # Find the first occurrence of a space that is followed by a
            # non-key=value word. We do this by splitting off the f:key=value
            # token as everything from f: up to the first space, but handle
            # multi-word filter values by checking if the next token contains
            # no alpha question words vs filter continuation.
            #
            # Robust fix: use the pattern f:key=value  (one token, no spaces
            # in value allowed unless user quotes) and document accordingly.
            # For "Global Tender" specifically, user should write:
            #   f:bid_type=Global Tender question...
            # We handle this by consuming tokens greedily into the value until
            # we hit a token that looks like a question word (not a capitalized
            # proper noun that extends the filter value).
            #
            # Simplest correct heuristic: the filter value is everything after
            # = in the first token. If the value is a known multi-word type
            # (contains no lowercase), keep consuming. Stop at first lowercase
            # word — that's the start of the question.
            rest = raw[2:]  # strip "f:"
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
                        # lowercase start → question begins here
                        found_question = True
                        question_tokens.append(tok)
                    else:
                        value_tokens.append(tok)
                value    = " ".join(value_tokens).strip()
                question = " ".join(question_tokens).strip()
                if key and value and question:
                    filters = {key.strip(): value}
                else:
                    # Couldn't parse cleanly — treat whole thing as question
                    question = raw
                    filters  = None

        result = engine.ask(question, filters=filters)
        _print_answer(result)


def run_reindex():
    from storage.database import BidDatabase
    from rag.vector_store import reindex_all
    db = BidDatabase()
    reindex_all(db)
    print("\nRe-index complete. Run --stats to verify.\n")


# =========================================================
# TENDER API PIPELINE COMMANDS
# =========================================================
def print_tender_stats():
    from tender_database import TenderDatabase
    db = TenderDatabase()
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


def run_tender_active(category: str = "", state: str = ""):
    from tender_pipeline import run_active
    run_active(category=category, state=state)


def run_tender_results(category: str = "", state: str = ""):
    from tender_pipeline import run_results
    run_results(category=category, state=state)


def run_tender_file(filepath: str):
    from tender_pipeline import run_from_file
    run_from_file(filepath)


if __name__ == "__main__":
    args = sys.argv[1:]

    try:
        if "--stats" in args:
            print_stats()

        elif "--tender-stats" in args:
            print_tender_stats()

        elif "--tender-file" in args:
            idx = args.index("--tender-file")
            fp  = args[idx + 1] if idx + 1 < len(args) else ""
            if fp:
                run_tender_file(fp)
            else:
                print("Usage: python main.py --tender-file path/to/file.json")

        elif "--tender-active" in args:
            cat   = args[args.index("--category") + 1] if "--category" in args else ""
            state = args[args.index("--state") + 1]    if "--state"    in args else ""
            run_tender_active(category=cat, state=state)

        elif "--tender-results" in args:
            cat   = args[args.index("--category") + 1] if "--category" in args else ""
            state = args[args.index("--state") + 1]    if "--state"    in args else ""
            run_tender_results(category=cat, state=state)

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
    except KeyboardInterrupt:
        print("\n")
        log.info("Process interrupted by user (Ctrl+C). Shutting down gracefully...")
        try:
            sys.exit(130)  # Standard Linux exit code for SIGINT
        except SystemExit:
            os._exit(130)