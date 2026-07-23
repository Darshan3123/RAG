# =========================================================
# pipeline/scheduler.py
# Scraper Scheduler & New Bid Notification Routine
# =========================================================
"""
GeM Bid Scraper Scheduler Module.

Orchestrates periodic background execution of the full bid scraping pipeline,
listens for graceful OS shutdown signals (SIGINT, SIGTERM), and alerts on newly
detected active bids.
"""

import time
import signal
import sys
from datetime import datetime
from config.settings import SCRAPE_INTERVAL_MINUTES
from pipeline.scraper import run_full_scrape
from storage.database import BidDatabase
from utils.logger import get_logger

log = get_logger("scheduler")

# Flag controlling continuous execution loop (toggled to False on shutdown signals)
_running = True


def _handle_signal(sig, frame):
    """
    Signal handler for OS signals (SIGINT, SIGTERM).
    
    Args:
        sig (int): Signal number received.
        frame (frame): Current stack frame object.
    """
    global _running
    log.info("Shutdown signal received — stopping scheduler after current run.")
    _running = False


# Register signal handlers for clean thread & process termination
signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# =========================================================
# NEW BID ALERT SUMMARY
# =========================================================
def alert_new_bids(db: BidDatabase):
    """
    Query the database for newly added bids from the latest scrape run,
    log a formatted alert summary, and mark them as seen.
    
    Args:
        db (BidDatabase): Active SQLite database connection manager.
    """
    new_bids = db.get_new_bids()
    if not new_bids:
        log.info("No new bids detected in this run.")
        return

    log.info("")
    log.info("🆕  NEW BIDS DETECTED THIS RUN")
    log.info("=" * 60)
    for bid in new_bids:
        log.info(
            f"  [{bid.get('bid_type', 'N/A')}] "
            f"{bid.get('bid_no', 'N/A')} | "
            f"{bid.get('full_item_name', '')[:50]} | "
            f"Dept: {bid.get('department', '')[:40]} | "
            f"End: {bid.get('end_date', 'N/A')}"
        )
    log.info("=" * 60)
    log.info(f"  Total new bids: {len(new_bids)}")

    # ── EXTENSION HOOK ────────────────────────────────────
    # Add external notification integrations here if needed:
    # e.g., send_email_alert(new_bids)
    # e.g., push_to_slack_webhook(new_bids)
    # ──────────────────────────────────────────────────────

    # Reset is_new status flag for all records
    db.mark_all_seen()


# =========================================================
# MAIN SCHEDULER LOOP
# =========================================================
def start_scheduler(run_once: bool = False):
    """
    Launch the scraper execution loop.
    
    Args:
        run_once (bool): If True, runs a single full scrape iteration and exits.
                         If False, runs continuously on configured time interval.
    """
    db = BidDatabase()
    interval_sec = SCRAPE_INTERVAL_MINUTES * 60

    log.info("")
    log.info("=" * 60)
    log.info("GEM BID SCRAPER SCHEDULER STARTED")
    log.info(f"Execution Interval: every {SCRAPE_INTERVAL_MINUTES} minutes")
    log.info(f"Database Target: {db.db_path}")
    log.info("=" * 60)

    while _running:
        run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.info(f"\n▶  Scrape run started at {run_at}")

        try:
            # 1. Execute full scraper pipeline
            run_full_scrape(db)
            
            # 2. Check and log summary of new bids
            alert_new_bids(db)
        except Exception as e:
            log.critical(f"Scrape run execution failed: {e}")

        # Exit loop if single-run mode is requested
        if run_once:
            log.info("Single run complete. Exiting scheduler.")
            break

        next_run = datetime.fromtimestamp(
            time.time() + interval_sec
        ).strftime("%H:%M:%S")
        log.info(
            f"\n⏱  Next scheduled run at {next_run} "
            f"(in {SCRAPE_INTERVAL_MINUTES} min). "
            f"Press Ctrl+C to stop."
        )

        # Sleep in 1-second ticks so process remains responsive to Ctrl+C (SIGINT)
        for _ in range(interval_sec):
            if not _running:
                break
            time.sleep(1)

    log.info("Scheduler loop terminated.")
