#!/usr/bin/env python3
# =========================================================
# scraper/main.py — Scraper module entry point
#
# Run from project root:   python scraper/main.py --once
# Run from module dir:     cd scraper && python main.py --once
#
# python main.py                          # continuous hourly loop
# python main.py --once                   # single scrape run
# python main.py --stats                  # MongoDB stats
# python main.py --tender-active          # fetch open tenders from API
# python main.py --tender-results         # fetch awarded tenders from API
# python main.py --tender-file path.json  # load tenders from local file
# python main.py --tender-stats           # tender collection stats
# python main.py --tender-active --category "Printing Work" --state Gujarat
# =========================================================
import sys
import os

# Works whether called from root (python scraper/main.py)
# or from inside the module dir (cd scraper && python main.py)
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from shared.utils.logger import get_logger
log = get_logger("main")


def print_stats():
    from shared.storage import mongo_client as db
    s = db.stats()
    print(f"\n{'='*42}\n  GeM Bid Scraper — Stats\n{'='*42}")
    print(f"  Total bids  : {s['total']}")
    print(f"  New (unseen): {s['new_this_run']}")
    print(f"  Total runs  : {s['total_runs']}")
    print(f"{'='*42}\n")


if __name__ == "__main__":
    args = sys.argv[1:]

    try:
        if "--stats" in args:
            print_stats()

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
                print("Usage: python main.py --tender-file path/to/file.json")

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
        log.info("Interrupted by user (Ctrl+C). Shutting down...")
        try:
            sys.exit(130)
        except SystemExit:
            os._exit(130)
