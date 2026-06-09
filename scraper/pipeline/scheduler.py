# =========================================================
# scraper/pipeline/scheduler.py
# Runs the scraper every SCRAPE_INTERVAL_MINUTES.
# No embedding model is loaded here — that lives in indexer/.
# =========================================================
import time
import signal
import sys
from datetime import datetime

from shared.config.settings import SCRAPE_INTERVAL_MINUTES
from shared.storage import mongo_client as db
from shared.utils.logger import get_logger
from scraper.pipeline.scraper import run_full_scrape

log = get_logger("scheduler")

_running = True

def _handle_signal(sig, frame):
    global _running
    log.info("Shutdown signal received — stopping after current run.")
    _running = False

signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


def alert_new_bids():
    new_bids = db.get_new_bids()
    if not new_bids:
        log.info("No new bids this run.")
        return

    log.info("")
    log.info("NEW BIDS DETECTED THIS RUN")
    log.info("=" * 60)
    for bid in new_bids:
        log.info(
            f"  [{bid.get('bid_type','')}] "
            f"{bid.get('bid_no','')} | "
            f"{bid.get('full_item_name','')[:50]} | "
            f"Dept: {bid.get('department','')[:40]} | "
            f"End: {bid.get('end_date','')}"
        )
    log.info("=" * 60)
    log.info(f"  Total new: {len(new_bids)}")

    # ── HOOK: add your notification here ──────────────────
    # e.g. send_email(new_bids)
    # e.g. send_whatsapp(new_bids)
    # e.g. post_to_slack(new_bids)
    # ──────────────────────────────────────────────────────

    # Note: we do NOT call mark_all_seen() here.
    # The indexer reads is_new=True to find bids to embed.
    # Only mark_bids_indexed() in the indexer clears the flag.


def start_scheduler(run_once: bool = False):
    """
    run_once=True  → single run then exit (for cron / testing)
    run_once=False → continuous loop every N minutes
    """
    interval_sec = SCRAPE_INTERVAL_MINUTES * 60

    log.info("=" * 60)
    log.info("GEM BID SCRAPER SCHEDULER STARTED")
    log.info(f"Interval: every {SCRAPE_INTERVAL_MINUTES} minutes")
    log.info(f"MongoDB:  {__import__('shared.config.settings', fromlist=['MONGO_URI']).MONGO_URI}")
    log.info("NOTE: Embedding/indexing runs separately on the GPU server.")
    log.info("      After scraping, run: python main.py --index-new  (on indexer)")
    log.info("=" * 60)

    while _running:
        run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.info(f"\n  Run started at {run_at}")

        try:
            run_full_scrape()
            alert_new_bids()
        except Exception as e:
            log.critical(f"Run failed: {e}")

        if run_once:
            log.info("Single run complete. Exiting.")
            break

        next_run = datetime.fromtimestamp(
            time.time() + interval_sec
        ).strftime("%H:%M:%S")
        log.info(
            f"\n  Next run at {next_run} "
            f"(in {SCRAPE_INTERVAL_MINUTES} min). "
            f"Press Ctrl+C to stop."
        )
        for _ in range(interval_sec):
            if not _running:
                break
            time.sleep(1)

    log.info("Scheduler stopped.")
