#!/usr/bin/env python3
# =========================================================
# query_main.py  —  Query entry point (run from root)
#
# python query_main.py --ask "show me open bids for printing"
# python query_main.py --ask "pumps in Gujarat" --filter state=Gujarat
# python query_main.py --chat
# python query_main.py --search "printing"
# python query_main.py --stats
# =========================================================
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.utils.logger import get_logger
log = get_logger("query_main")


def _print_answer(result: dict):
    print("\n" + "─" * 62)
    print(result["answer"])
    print(f"\n── Sources ({len(result['sources'])} unique bids) ──")
    for s in result["sources"]:
        meta = " | ".join(filter(None, [s.get("sector",""), s.get("state",""), s.get("status","")]))
        print(
            f"  [{s['bid_no']}]  "
            f"{s['department'][:35]}  "
            f"Score: {s['relevance_score']:.2%}"
            + (f"  [{meta}]" if meta else "")
        )
    print("─" * 62 + "\n")


def run_ask(question: str, filter_str: str | None):
    from query.rag.query_engine import QueryEngine
    filters = None
    if filter_str:
        kv = filter_str.split("=", 1)
        if len(kv) == 2:
            key = kv[0].strip()
            val = kv[1].strip()
            key_aliases = {"tender_status": "status", "dept": "department"}
            filters = {key_aliases.get(key, key): val}
    engine = QueryEngine()
    result = engine.ask(question, filters=filters)
    print(f"\nQ: {result['question']}")
    if filters:
        print(f"   Filters: {filters}")
    _print_answer(result)


def run_chat():
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
                key, after_eq = rest.split("=", 1)
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


def print_stats():
    from query.rag.vector_store import stats as vs_stats
    vs = vs_stats()
    print(f"\n{'='*42}\n  Query — Stats\n{'='*42}")
    print(f"  ChromaDB chunks    : {vs['total_chunks']}")
    print(f"  ChromaDB collection: {vs['collection']}")
    print(f"  ChromaDB path      : {vs['chroma_dir']}")
    print(f"{'='*42}\n")


if __name__ == "__main__":
    args = sys.argv[1:]

    try:
        if "--stats" in args:
            print_stats()

        elif "--ask" in args:
            idx        = args.index("--ask")
            question   = args[idx + 1] if idx + 1 < len(args) else ""
            filter_str = None
            if "--filter" in args:
                fi            = args.index("--filter")
                filter_tokens = []
                j = fi + 1
                while j < len(args) and not args[j].startswith("--"):
                    filter_tokens.append(args[j])
                    j += 1
                filter_str = " ".join(filter_tokens) if filter_tokens else None
            if question:
                run_ask(question, filter_str)
            else:
                print('Usage: python query_main.py --ask "your question"')

        elif "--chat" in args:
            run_chat()

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
                print('Usage: python query_main.py --search "keywords"')

        else:
            print("""
Usage:
  python query_main.py --ask "question"
  python query_main.py --ask "question" --filter state=Gujarat
  python query_main.py --chat
  python query_main.py --search "keywords"
  python query_main.py --stats
            """)

    except KeyboardInterrupt:
        print("\n")
        sys.exit(130)
