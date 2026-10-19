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
def scrape_category(self, bid_type: str = "Product Bid/RAs", target_count: int = TARGET_PER_TYPE) -> Dict[str, Any]:
    """
    Tier 1 Worker Task:
    1. Launches Playwright browser context.
    2. Navigates to GeM portal and selects bid_type filter.
    3. Crawls cards, checks Redis deduplication key (`gem:seen:{safe_bid_no}`).
    4. Downloads Bid & RA PDFs and extracts hyperlinks.
    5. Dispatches Tier 2 task (`tasks.tier2_document.process_document`) to document_queue.
    """
    log.info(f"[Tier 1] Starting scrape for category: '{bid_type}' (Target: {target_count})")
    r = _get_redis_client()
    dispatched = 0
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

        while dispatched < target_count and empty_pages < MAX_EMPTY_PAGES:
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
                if dispatched >= target_count:
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
                        log.info(f"[Tier 1] Tender {safe_bid_no} already processed, skipping")
                        continue

                    # Mark in-progress in Redis (7 days TTL)
                    r.set(dedup_key, "downloading", ex=86400 * 7)

                    # Create local folder
                    # Save HTML snippet to MinIO S3
                    card_html = card.inner_html()
                    try:
                        from utils.s3_storage import upload_bytes as s3_upload_bytes
                        s3_upload_bytes(f"bids/{safe_bid_no}/card.html", card_html.encode("utf-8"), content_type="text/html")
                    except Exception as e:
                        log.warning(f"Could not save card HTML to MinIO for {safe_bid_no}: {e}")

                    # Download Main Bid PDF directly into memory
                    pdf_bytes = browser.download_pdf_to_memory(doc_url, retries=MAX_RETRIES_PER_BID)
                    if not pdf_bytes:
                        log.warning(f"[Tier 1] Download failed for {safe_bid_no}")
                        r.delete(dedup_key)
                        continue

                    # Stream PDF to MinIO S3
                    s3_pdf_key = f"bids/{safe_bid_no}/bid.pdf"
                    from utils.s3_storage import upload_bytes as s3_upload_bytes
                    s3_upload_bytes(s3_pdf_key, pdf_bytes, content_type="application/pdf")

                    # Download RA PDF if available
                    if ra_url:
                        ra_bytes = browser.download_pdf_to_memory(ra_url, retries=MAX_RETRIES_PER_BID)
                        if ra_bytes:
                            s3_upload_bytes(f"bids/{safe_bid_no}/bid_RA.pdf", ra_bytes, content_type="application/pdf")

                    # Extract Hyperlinks in memory
                    bid_hyperlinks: List[Dict[str, Any]] = []
                    try:
                        bid_hyperlinks = extract_hyperlinks(pdf_bytes, source="bid")
                    except Exception as e:
                        log.warning(f"Hyperlink extraction failed for {safe_bid_no}: {e}")

                    if "card" in card_data:
                        card_data["card"]["bid_pdf_url"] = doc_url
                        card_data["card"]["ra_pdf_url"] = ra_url

                    # Dispatch to Tier 2 (document_queue)
                    from tasks.tier2_document import process_document
                    process_document.delay(
                        safe_bid_no=safe_bid_no,
                        card_data=card_data,
                        pdf_path=f"s3://gem-tenders/{s3_pdf_key}",
                        bid_hyperlinks=bid_hyperlinks,
                        card_html=card_html,
                    )

                    dispatched += 1
                    scraped_bids.append(safe_bid_no)
                    log.info(f"[Tier 1] Dispatched tender {safe_bid_no} to Tier 2 (document_queue)")
                    sleep_between_cards()

                except Exception as card_err:
                    log.error(f"[Tier 1] Error processing card: {card_err}", exc_info=True)

            if dispatched < target_count:
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
def crawl_all_categories(target_per_category: int = 2) -> Dict[str, Any]:
    """
    Celery Beat Clock Task:
    Iterates through all 9 GeM categories and schedules scrape tasks.
    """
    log.info(f"[Tier 1] Enqueuing periodic crawl for {len(BID_TYPES)} categories")
    tasks = []
    for cat in BID_TYPES:
        t = scrape_category.delay(bid_type=cat, target_count=target_per_category)
        tasks.append((cat, t.id))
    return {"status": "enqueued", "tasks": tasks}


@app.task(name="tasks.tier1_scraper.scrape_single_bid", bind=True, max_retries=2)
def scrape_single_bid(self, bid_no: str) -> Dict[str, Any]:
    """
    Tier 1 Worker Task: On-demand crawl for a specific bid number.
    1. Uses advanced_search_bid to locate the tender card.
    2. Downloads Bid & RA PDFs and extracts hyperlinks.
    3. Dispatches Tier 2 task to document_queue.
    """
    log.info(f"[Tier 1] Starting on-demand scrape for bid: '{bid_no}'")
    safe_bid_no = bid_no.replace("/", "_")
    r = _get_redis_client()
    dedup_key = f"gem:seen:{safe_bid_no}"
    r.set(dedup_key, "downloading", ex=86400 * 7)

    browser = GemBrowser()
    try:
        browser.start()
        browser.advanced_search_bid(bid_no)
        browser.wait_for_cards()
        cards = browser.get_all_cards()
        if not cards:
            log.warning(f"[Tier 1] No cards found for bid: {bid_no}")
            return {"status": "not_found", "bid_no": bid_no}

        card = cards[0]
        card_data = get_card_details(card, "Direct Search")
        doc_url, ra_url, corr_url = browser.extract_card_links(card)

        s3_pdf_key = f"bids/{safe_bid_no}/bid.pdf"
        pdf_bytes = None
        if doc_url:
            pdf_bytes = browser.download_pdf_to_memory(doc_url, retries=MAX_RETRIES_PER_BID)
            if pdf_bytes:
                try:
                    from utils.s3_storage import upload_bytes as s3_upload_bytes
                    s3_upload_bytes(s3_pdf_key, pdf_bytes, content_type="application/pdf")
                except Exception as s3_err:
                    log.warning(f"[Tier 1] MinIO upload failed for {safe_bid_no}: {s3_err}")

        bid_hyperlinks = []
        if pdf_bytes:
            try:
                bid_hyperlinks = extract_hyperlinks(pdf_bytes)
            except Exception as h_err:
                log.warning(f"[Tier 1] Hyperlink extraction error: {h_err}")

        card_html = card.inner_html() if hasattr(card, "inner_html") else ""
        if card_html:
            try:
                from utils.s3_storage import upload_bytes as s3_upload_bytes
                s3_upload_bytes(f"bids/{safe_bid_no}/card.html", card_html.encode("utf-8"), content_type="text/html")
            except Exception:
                pass

        from tasks.tier2_document import process_document
        task = process_document.delay(
            safe_bid_no=safe_bid_no,
            card_data=card_data,
            pdf_path=f"s3://gem-tenders/{s3_pdf_key}",
            bid_hyperlinks=bid_hyperlinks,
            card_html=card_html,
        )

        return {"status": "enqueued", "bid_no": bid_no, "document_task_id": task.id}
    finally:
        browser.close()
