#!/usr/bin/env python3
# =========================================================
# main.py  —  Unified entry point (run from root)
#
# ── SCRAPER ──────────────────────────────────────────────
# python main.py --scrape                          # continuous loop
# python main.py --scrape --once                   # single scrape run
# python main.py --scrape --stats                  # MongoDB stats
# python main.py --scrape --tender-active          # fetch open tenders
# python main.py --scrape --tender-results         # fetch awarded tenders
# python main.py --scrape --tender-file path.json  # load from local file
# python main.py --scrape --tender-stats           # tender collection stats
# python main.py --scrape --tender-active --category "Printing Work" --state Gujarat
#
# ── EXPORT ───────────────────────────────────────────────
# python main.py --export                          # export to output.json (default)
# python main.py --export --out my_file.json       # export to custom path
#
# ── INDEXER ──────────────────────────────────────────────
# python main.py --index --index-new               # embed new bids
# python main.py --index --reindex-all             # rebuild ChromaDB
# python main.py --index --stats                   # MongoDB + ChromaDB stats
#
# ── QUERY ────────────────────────────────────────────────
# python main.py --query --ask "show me open bids for printing"
# python main.py --query --ask "pumps in Gujarat" --filter state=Gujarat
# python main.py --query --chat
# python main.py --query --search "keywords"
# python main.py --query --stats
# =========================================================
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HELP = """
GeM Scraper — Unified Entry Point
==================================

SCRAPER commands:
  python main.py --scrape                           continuous hourly loop
  python main.py --scrape --once                    single scrape run
  python main.py --scrape --stats                   MongoDB stats
  python main.py --scrape --tender-active           fetch open tenders from API
  python main.py --scrape --tender-results          fetch awarded tenders from API
  python main.py --scrape --tender-file path.json   load tenders from local file
  python main.py --scrape --tender-stats            tender collection stats
  python main.py --scrape --tender-active --category "Printing Work" --state Gujarat

EXPORT commands:
  python main.py --export                           export all bids to output.json
  python main.py --export --out my_file.json        export to a custom path

INDEXER commands:
  python main.py --index --index-new                embed new bids into ChromaDB
  python main.py --index --reindex-all              rebuild entire ChromaDB from scratch
  python main.py --index --stats                    MongoDB + ChromaDB stats

QUERY commands:
  python main.py --query --ask "question"           RAG answer with LLM
  python main.py --query --ask "q" --filter state=Gujarat
  python main.py --query --chat                     interactive chat
  python main.py --query --search "keywords"        retrieval only, no LLM
  python main.py --query --stats                    ChromaDB stats

Or run each module directly from root:
  python scraper_main.py --once
  python indexer_main.py --index-new
  python query_main.py   --chat

Or run from inside the module directory:
  cd scraper  &&  python main.py --once
  cd indexer  &&  python main.py --index-new
  cd query    &&  python main.py --chat
"""


# ── SCRAPER ───────────────────────────────────────────────────────────────────

def run_scraper(args: list):
    from shared.utils.logger import get_logger
    log = get_logger("main.scraper")

    try:
        if "--stats" in args:
            from shared.storage import mongo_client as db
            s = db.stats()
            print(f"\n{'='*42}\n  GeM Bid Scraper — Stats\n{'='*42}")
            print(f"  Total bids  : {s['total']}")
            print(f"  New (unseen): {s['new_this_run']}")
            print(f"  Total runs  : {s['total_runs']}")
            print(f"{'='*42}\n")

        elif "--tender-stats" in args:
            from scraper.pipeline.tender_pipeline import tender_stats
            tender_stats()

        elif "--tender-file" in args:
            idx = args.index("--tender-file")
            fp  = args[idx + 1] if idx + 1 < len(args) else ""
            if fp:
                from scraper.pipeline.tender_pipeline import run_from_file
                run_from_file(fp)
            else:
                print("Usage: python main.py --scrape --tender-file path/to/file.json")

        elif "--tender-active" in args:
            cat   = args[args.index("--category") + 1] if "--category" in args else ""
            state = args[args.index("--state")    + 1] if "--state"    in args else ""
            from scraper.pipeline.tender_pipeline import run_active
            run_active(category=cat, state=state)

        elif "--tender-results" in args:
            cat   = args[args.index("--category") + 1] if "--category" in args else ""
            state = args[args.index("--state")    + 1] if "--state"    in args else ""
            from scraper.pipeline.tender_pipeline import run_results
            run_results(category=cat, state=state)

        elif "--once" in args:
            log.info("Mode: single scrape run")
            from scraper.pipeline.scheduler import start_scheduler
            start_scheduler(run_once=True)

        else:
            log.info("Mode: continuous hourly loop")
            from scraper.pipeline.scheduler import start_scheduler
            start_scheduler(run_once=False)

    except KeyboardInterrupt:
        print("\n")
        log.info("Scraper interrupted.")
        try:
            sys.exit(130)
        except SystemExit:
            os._exit(130)



# ── EXPORT ────────────────────────────────────────────────────────────────────

def run_export(args: list):
    from shared.storage import mongo_client as db

    out_path = "output.json"
    if "--out" in args:
        idx = args.index("--out")
        if idx + 1 < len(args):
            out_path = args[idx + 1]

    db.export_json(out_path)
    total = db.stats()["total"]
    print(f"\n✅  Exported {total} records → {out_path}\n")


# ── INDEXER ───────────────────────────────────────────────────────────────────

def run_indexer(args: list):
    from shared.utils.logger import get_logger
    log = get_logger("main.indexer")

    try:
        if "--stats" in args:
            from shared.storage import mongo_client as db
            from indexer.rag.vector_store import stats as vs_stats
            s  = db.stats()
            vs = vs_stats()
            print(f"\n{'='*42}\n  Indexer — Stats\n{'='*42}")
            print(f"  MongoDB total bids    : {s['total']}")
            print(f"  Unindexed (is_new)    : {s['new_this_run']}")
            print(f"  ChromaDB product chunks : {vs['product_chunks']}")
            print(f"  ChromaDB service chunks : {vs['service_chunks']}")
            print(f"  ChromaDB collections  : {', '.join(vs['collections'])}")
            print(f"  ChromaDB path         : {vs['chroma_dir']}")
            print(f"{'='*42}\n")

        elif "--reindex-all" in args:
            log.info("Mode: full reindex from MongoDB")
            from shared.storage import mongo_client as db
            from indexer.rag.vector_store import reindex_all as vs_reindex
            from shared.rag.embedder import prewarm_model
            bids = db.get_all(projection={"_id": 0})
            log.info(f"Reindexing {len(bids)} bids...")
            prewarm_model()
            vs_reindex(bids)
            log.info("Full reindex complete.")

        elif "--index-new" in args:
            log.info("Mode: index new bids only")
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
            for i, bid in enumerate(new_bids, 1):
                try:
                    log.info(f"  [{i}/{len(new_bids)}] {bid.get('bid_no','unknown')}")
                    upsert_bid(bid)
                    indexed_urls.append(bid["document_url"])
                except Exception as e:
                    log.error(f"  Failed: {bid.get('bid_no','?')}: {e}")
            db.mark_bids_indexed(indexed_urls)
            log.info(f"Done. Indexed {len(indexed_urls)}/{len(new_bids)} bids.")

        else:
            print("""
Indexer usage:
  python main.py --index --index-new
  python main.py --index --reindex-all
  python main.py --index --stats
            """)

    except KeyboardInterrupt:
        print("\n")
        log.info("Indexer interrupted.")
        sys.exit(130)


# ── QUERY ─────────────────────────────────────────────────────────────────────

def run_query(args: list):
    from shared.utils.logger import get_logger
    log = get_logger("main.query")

    def _print_answer(result: dict):
        print("\n" + "-" * 62)
        print(result["answer"])
        print(f"\n-- Sources ({len(result['sources'])} unique bids) --")
        for s in result["sources"]:
            meta = " | ".join(filter(None, [s.get("sector",""), s.get("state",""), s.get("status","")]))
            print(
                f"  [{s['bid_no']}]  "
                f"{s['department'][:35]}  "
                f"Score: {s['relevance_score']:.2%}"
                + (f"  [{meta}]" if meta else "")
            )
        print("-" * 62 + "\n")

    try:
        if "--stats" in args:
            from query.rag.vector_store import stats as vs_stats
            vs = vs_stats()
            print(f"\n{'='*42}\n  Query — Stats\n{'='*42}")
            print(f"  ChromaDB chunks    : {vs['total_chunks']}")
            print(f"  ChromaDB collection: {vs['collection']}")
            print(f"  ChromaDB path      : {vs['chroma_dir']}")
            print(f"{'='*42}\n")

        elif "--ask" in args:
            idx      = args.index("--ask")
            question = args[idx + 1] if idx + 1 < len(args) else ""
            filter_str = None
            if "--filter" in args:
                fi            = args.index("--filter")
                filter_tokens = []
                j = fi + 1
                while j < len(args) and not args[j].startswith("--"):
                    filter_tokens.append(args[j])
                    j += 1
                filter_str = " ".join(filter_tokens) if filter_tokens else None

            if not question:
                print('Usage: python main.py --query --ask "your question"')
                return

            filters = None
            if filter_str:
                kv = filter_str.split("=", 1)
                if len(kv) == 2:
                    key = kv[0].strip()
                    val = kv[1].strip()
                    key_aliases = {"tender_status": "status", "dept": "department"}
                    filters = {key_aliases.get(key, key): val}

            from query.rag.query_engine import QueryEngine
            engine = QueryEngine()
            result = engine.ask(question, filters=filters)
            print(f"\nQ: {result['question']}")
            if filters:
                print(f"   Filters: {filters}")
            _print_answer(result)

        elif "--chat" in args:
            from query.rag.query_engine import QueryEngine, is_exit
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

                if not raw or is_exit(raw):
                    print("Bye.")
                    break

                if raw.lower().startswith("/search "):
                    q       = raw[8:].strip()
                    results = engine.search_only(q)
                    print(f"\n{len(results)} unique bids:\n")
                    for r in results:
                        item = r.get("full_item_name", "N/A")[:40]
                        print(
                            f"  • {r['bid_no']:30s} "
                            f"| {item:40s} "
                            f"| End: {r.get('end_date','N/A'):19s} "
                            f"| {r['score']:.2%}"
                        )
                    print()
                    continue

                filters  = None
                question = raw
                if raw.startswith("f:"):
                    rest = raw[2:]
                    if "=" in rest:
                        key, after_eq   = rest.split("=", 1)
                        tokens          = after_eq.split(" ")
                        value_tokens    = []
                        question_tokens = []
                        found_q         = False
                        for tok in tokens:
                            if found_q:
                                question_tokens.append(tok)
                            elif tok and tok[0].islower():
                                found_q = True
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

        elif "--search" in args:
            idx = args.index("--search")
            q   = args[idx + 1] if idx + 1 < len(args) else ""
            if q:
                from query.rag.query_engine import QueryEngine
                engine  = QueryEngine()
                results = engine.search_only(q)
                for r in results:
                    print(f"  • {r['bid_no']} | {r.get('full_item_name','')[:50]} | {r['score']:.2%}")
            else:
                print('Usage: python main.py --query --search "keywords"')

        else:
            print("""
Query usage:
  python main.py --query --ask "question"
  python main.py --query --ask "question" --filter state=Gujarat
  python main.py --query --chat
  python main.py --query --search "keywords"
  python main.py --query --stats
            """)

    except KeyboardInterrupt:
        print("\n")
        sys.exit(130)


# ── ROUTER ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print(HELP)

    elif "--scrape" in args:
        remaining = [a for a in args if a != "--scrape"]
        run_scraper(remaining)

    elif "--export" in args:
        remaining = [a for a in args if a != "--export"]
        run_export(remaining)

    elif "--index" in args:
        remaining = [a for a in args if a != "--index"]
        run_indexer(remaining)

    elif "--query" in args:
        remaining = [a for a in args if a != "--query"]
        run_query(remaining)

    else:
        print(f"Unknown command: {' '.join(args)}")
        print(HELP)
