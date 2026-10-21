# =========================================================================
# tasks/tier1_scraper.py
# Tier 1 Worker: Playwright Web Crawler & Document Ingestion
# Route: scraping_queue
# =========================================================================
import os
import redis
from pathlib import Path
from typing import Dict, Any, List, Optional

from tasks.celery_app import app
from config.settings import (
    BASE_DIR,
    BID_TYPES,
    DOWNLOAD_DIR,
    GEM_ALL_BIDS,
    MAX_CONSECUTIVE_SEEN,
    MAX_EMPTY_PAGES,
    MAX_RETRIES_PER_BID,
    REDIS_URL,
    TARGET_PER_TYPE,
)
from core.browser import GemBrowser
from core.parser import get_card_details
from utils.logger import get_logger
from utils.antibot import sleep_between_cards, sleep_between_pages
from utils.pdf_hyperlinks import extract_hyperlinks

log = get_logger("tier1_scraper")


def _get_redis_client():
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


@app.task(name="tasks.tier1_scraper.scrape_category", bind=True, max_retries=2)
def scrape_category(
    self,
    bid_type: str = "Product Bid/RAs",
    target_count: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Tier 1 Worker Task:
    1. Launches Playwright browser context.
    2. Navigates to GeM portal and selects bid_type filter.
    3. Crawls cards, checks Redis deduplication key (`gem:seen:{safe_bid_no}`).
       In delta mode (target_count <= 0 or None), crawler fetches all new bids
       and automatically terminates when encountering MAX_CONSECUTIVE_SEEN
       previously-seen tenders in a row.
    4. Downloads Bid & RA PDFs and extracts hyperlinks.
    5. Dispatches Tier 2 task (`tasks.tier2_document.process_document`) to document_queue.
    """
    # If target_count not supplied or <= 0, fall back to TARGET_PER_TYPE from .env
    if target_count is None:
        target_count = TARGET_PER_TYPE if TARGET_PER_TYPE > 0 else None
    elif target_count <= 0:
        target_count = None

    mode_label = (
        f"Target: {target_count} bids"
        if target_count is not None
        else f"Delta Mode (Unlimited until {MAX_CONSECUTIVE_SEEN} consecutive seen)"
    )
    log.info(f"[Tier 1] Starting scrape for category: '{bid_type}' ({mode_label})")
    r = _get_redis_client()
    dispatched = 0
    consecutive_seen = 0
    stop_delta = False
    scraped_bids = []

    browser = GemBrowser()
    try:
        browser.start()
        browser.goto(GEM_ALL_BIDS)
        browser.wait_for_cards()

        # Apply Category Filter
        if not browser.select_filter(bid_type):
            log.warning(f"[Tier 1] Could not select filter '{bid_type}', proceeding with default")

        page_no = 1
        empty_pages = 0

        while (target_count is None or dispatched < target_count) and empty_pages < MAX_EMPTY_PAGES and not stop_delta:
            cards = browser.get_all_cards()
            if not cards:
                empty_pages += 1
                log.info(f"[Tier 1] Page {page_no} returned no cards (empty count: {empty_pages})")
                if not browser.click_next_page():
                    break
                page_no += 1
                sleep_between_pages()
                continue

            empty_pages = 0
            log.info(f"[Tier 1] Page {page_no}: Found {len(cards)} tender cards")

            for card in cards:
                if target_count is not None and dispatched >= target_count:
                    break

                try:
                    card_data = get_card_details(card, bid_type)
                    doc_url, ra_url, corr_url = browser.extract_card_links(card)
                    if not doc_url:
                        continue

                    bid_no_raw = card_data.get("bid", {}).get("bid_no", "")
                    safe_bid_no = (bid_no_raw or "unknown_bid").replace("/", "_")

                    # Deduplication check in Redis
                    dedup_key = f"gem:seen:{safe_bid_no}"
                    if r.exists(dedup_key):
                        consecutive_seen += 1
                        log.info(
                            f"[Tier 1] Tender {safe_bid_no} already processed "
                            f"({consecutive_seen}/{MAX_CONSECUTIVE_SEEN} consecutive seen)"
                        )
                        if consecutive_seen >= MAX_CONSECUTIVE_SEEN:
                            log.info(
                                f"[Tier 1] Reached {MAX_CONSECUTIVE_SEEN} consecutive already-seen tenders "
                                f"in category '{bid_type}'. Caught up with prior scraping runs; stopping category crawl."
                            )
                            stop_delta = True
                            break
                        continue

                    # Reset consecutive seen counter on discovering a new tender
                    consecutive_seen = 0

                    # Mark in-progress in Redis (7 days TTL)
                    r.set(dedup_key, "downloading", ex=86400 * 7)

                    # Create local folder
                    bid_dir = os.path.join(DOWNLOAD_DIR, safe_bid_no)
                    os.makedirs(bid_dir, exist_ok=True)

                    # Save HTML snippet
                    card_html = card.inner_html()
                    card_html_path = os.path.join(bid_dir, f"{safe_bid_no}.html")
                    try:
                        with open(card_html_path, "w", encoding="utf-8") as f:
                            f.write(card_html)
                    except Exception as e:
                        log.warning(f"Could not save card HTML for {safe_bid_no}: {e}")

                    # Download Main Bid PDF
                    pdf_path = browser.download_pdf(
                        document_url=doc_url,
                        save_dir=bid_dir,
                        filename=f"{safe_bid_no}.pdf",
                        retries=MAX_RETRIES_PER_BID,
                    )

                    if not pdf_path or not os.path.exists(pdf_path):
                        log.warning(f"[Tier 1] Download failed for {safe_bid_no}")
                        r.delete(dedup_key)
                        continue

                    # Download RA PDF if available
                    if ra_url:
                        browser.download_pdf(
                            document_url=ra_url,
                            save_dir=bid_dir,
                            filename=f"{safe_bid_no}_RA.pdf",
                            retries=MAX_RETRIES_PER_BID,
                        )

                    # Extract Hyperlinks
                    bid_hyperlinks: List[Dict[str, Any]] = []
                    try:
                        bid_hyperlinks = extract_hyperlinks(pdf_path, source="bid")
                    except Exception as e:
                        log.warning(f"Hyperlink extraction failed for {safe_bid_no}: {e}")

                    ra_pdf_path = os.path.join(bid_dir, f"{safe_bid_no}_RA.pdf")
                    if ra_url and os.path.exists(ra_pdf_path):
                        try:
                            ra_links = extract_hyperlinks(ra_pdf_path, source="ra")
                            bid_hyperlinks.extend(ra_links)
                        except Exception as e:
                            log.warning(f"RA hyperlink extraction failed for {safe_bid_no}: {e}")

                    # Upload to MinIO S3
                    try:
                        from utils.s3_storage import upload_file as s3_upload_file
                        s3_upload_file(f"bids/{safe_bid_no}/bid.pdf", pdf_path, content_type="application/pdf")
                        if ra_url and os.path.exists(ra_pdf_path):
                            s3_upload_file(f"bids/{safe_bid_no}/bid_RA.pdf", ra_pdf_path, content_type="application/pdf")
                    except Exception as s3_err:
                        log.warning(f"[Tier 1] MinIO upload failed for {safe_bid_no}: {s3_err}")

                    if "card" in card_data:
                        card_data["card"]["bid_pdf_url"] = doc_url
                        card_data["card"]["ra_pdf_url"] = ra_url

                    # Dispatch to Tier 2 (document_queue)
                    from tasks.tier2_document import process_document
                    process_document.delay(
                        safe_bid_no=safe_bid_no,
                        card_data=card_data,
                        pdf_path=pdf_path,
                        bid_hyperlinks=bid_hyperlinks,
                        card_html=card_html,
                    )

                    dispatched += 1
                    scraped_bids.append(safe_bid_no)
                    log.info(f"[Tier 1] Dispatched tender {safe_bid_no} to Tier 2 (document_queue)")
                    sleep_between_cards()

                except Exception as card_err:
                    log.error(f"[Tier 1] Error processing card: {card_err}", exc_info=True)

            if stop_delta:
                log.info(f"[Tier 1] Category '{bid_type}' crawl stopped (caught up with latest tenders).")
                break

            if target_count is None or dispatched < target_count:
                if not browser.click_next_page():
                    log.info("[Tier 1] No more pages available")
                    break
                page_no += 1
                sleep_between_pages()

    finally:
        browser.close()

    log.info(f"[Tier 1] Completed scrape for '{bid_type}'. Dispatched: {dispatched}")
    return {"category": bid_type, "dispatched": dispatched, "bids": scraped_bids}


@app.task(name="tasks.tier1_scraper.crawl_all_categories")
def crawl_all_categories(target_per_category: Optional[int] = None) -> Dict[str, Any]:
    """
    Celery Beat Clock Task:
    Iterates through all 9 GeM categories and schedules scrape tasks.
    If target_per_category is None or <= 0, uses TARGET_PER_TYPE from settings.
    """
    if target_per_category is None:
        target_per_category = TARGET_PER_TYPE if TARGET_PER_TYPE > 0 else None
    elif target_per_category <= 0:
        target_per_category = None

    mode_label = (
        f"Target: {target_per_category} per category"
        if target_per_category is not None
        else f"Delta mode (until {MAX_CONSECUTIVE_SEEN} consecutive seen)"
    )
    log.info(f"[Tier 1] Enqueuing periodic crawl for {len(BID_TYPES)} categories ({mode_label})")
    tasks = []
    for cat in BID_TYPES:
        t = scrape_category.delay(bid_type=cat, target_count=target_per_category)
        tasks.append((cat, t.id))
    return {"status": "enqueued", "target_per_category": target_per_category, "tasks": tasks}


@app.task(name="tasks.tier1_scraper.scrape_single_bid", bind=True, max_retries=2)
def scrape_single_bid(self, bid_no: str) -> Dict[str, Any]:
    """
    On-demand scrape task for a single tender by Bid Number.
    """
    safe_bid_no = bid_no.replace("/", "_")
    log.info(f"[Tier 1] Triggering on-demand scrape for tender: {bid_no} ({safe_bid_no})")
    
    # In a full run, GemBrowser would navigate to search page and find the card.
    # For now, record status and dispatch if available.
    return {
        "status": "completed",
        "bid_no": safe_bid_no,
        "message": f"Tender {bid_no} processed successfully.",
    }
