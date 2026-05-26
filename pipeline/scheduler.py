# =========================================================
# pipeline/scheduler.py
# Runs scraper every SCRAPE_INTERVAL_MINUTES
# Detects NEW bids and prints an alert summary
# =========================================================
import time
import signal
import sys
from datetime import datetime
from config.settings import SCRAPE_INTERVAL_MINUTES
from pipeline.scraper import run_full_scrape
from storage.database import BidDatabase
from utils.logger import get_logger

log = get_logger("scheduler")

# graceful shutdown on Ctrl+C or kill
_running = True

def _handle_signal(sig, frame):
    global _running
    log.info("Shutdown signal received — stopping after current run.")
    _running = False

signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# =========================================================
# NEW BID ALERT SUMMARY
# Prints (or sends — hook your notifier here) new bids
# =========================================================
def alert_new_bids(db: BidDatabase):
    new_bids = db.get_new_bids()
    if not new_bids:
        log.info("No new bids this run.")
        return

    log.info("")
    log.info("🆕  NEW BIDS DETECTED THIS RUN")
    log.info("=" * 60)
    for bid in new_bids:
        log.info(
            f"  [{bid['bid_type']}] "
            f"{bid['bid_no']} | "
            f"{bid['full_item_name'][:50]} | "
            f"Dept: {bid['department'][:40]} | "
            f"End: {bid['end_date']}"
        )
    log.info("=" * 60)
    log.info(f"  Total new: {len(new_bids)}")

    # ── HOOK: add your notification here ──────────────────
    # e.g. send_email(new_bids)
    # e.g. send_whatsapp(new_bids)
    # e.g. post_to_slack(new_bids)
    # e.g. push_to_webhook(new_bids)
    # ──────────────────────────────────────────────────────

    db.mark_all_seen()


# =========================================================
# MAIN SCHEDULER LOOP
# =========================================================
def start_scheduler(run_once: bool = False):
    """
    run_once=True  → single run then exit (for testing/cron)
    run_once=False → continuous loop every N minutes
    """
    db = BidDatabase()
    interval_sec = SCRAPE_INTERVAL_MINUTES * 60

    log.info("")
    log.info("=" * 60)
    log.info("GEM BID SCRAPER SCHEDULER STARTED")
    log.info(f"Interval: every {SCRAPE_INTERVAL_MINUTES} minutes")
    log.info(f"Database: {db.db_path}")
    log.info("=" * 60)

    while _running:
        run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.info(f"\n▶  Run started at {run_at}")

        try:
            run_full_scrape(db)
            alert_new_bids(db)
        except Exception as e:
            log.critical(f"Run failed: {e}")

        if run_once:
            log.info("Single run complete. Exiting.")
            break

        next_run = datetime.fromtimestamp(
            time.time() + interval_sec
        ).strftime("%H:%M:%S")
        log.info(
            f"\n⏱  Next run at {next_run} "
            f"(in {SCRAPE_INTERVAL_MINUTES} min). "
            f"Press Ctrl+C to stop."
        )

        # sleep in 1-second ticks so Ctrl+C is responsive
        for _ in range(interval_sec):
            if not _running:
                break
            time.sleep(1)

    log.info("Scheduler stopped.")
