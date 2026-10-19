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

        bid_dir = os.path.join(DOWNLOAD_DIR, safe_bid_no)
        os.makedirs(bid_dir, exist_ok=True)
        pdf_path = os.path.join(bid_dir, "bid.pdf")

        if doc_url:
            browser.download_pdf(doc_url, save_dir=bid_dir, filename="bid.pdf")
            try:
                from utils.s3_storage import upload_file as s3_upload_file
                s3_upload_file(f"bids/{safe_bid_no}/bid.pdf", pdf_path, content_type="application/pdf")
            except Exception as s3_err:
                log.warning(f"[Tier 1] MinIO upload failed for {safe_bid_no}: {s3_err}")

        bid_hyperlinks = []
        if os.path.exists(pdf_path):
            try:
                bid_hyperlinks = extract_hyperlinks(pdf_path)
            except Exception as h_err:
                log.warning(f"[Tier 1] Hyperlink extraction error: {h_err}")

        card_html = card.inner_html() if hasattr(card, "inner_html") else ""

        from tasks.tier2_document import process_document
        task = process_document.delay(
            safe_bid_no=safe_bid_no,
            card_data=card_data,
            pdf_path=pdf_path,
            bid_hyperlinks=bid_hyperlinks,
            card_html=card_html,
        )

        return {"status": "enqueued", "bid_no": bid_no, "document_task_id": task.id}
    finally:
        browser.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="GeMBridge Tier 1 Playwright Crawler CLI")
    parser.add_argument("--once", action="store_true", help="Run once and exit cleanly")
    parser.add_argument("--bid-type", type=str, default="Product Bid/RAs", help="GeM category/bid type to scrape (e.g. 'Product Bid/RAs', 'Service Bid/RAs', 'BOQ Bids')")
    parser.add_argument("--target", type=int, default=2, help="Target count of new tenders to scrape (default: 2)")
    parser.add_argument("--bid-no", type=str, default=None, help="Scrape a specific tender on-demand by Bid Number")
    parser.add_argument("--enqueue", action="store_true", help="Dispatch asynchronously to Celery scraping_queue instead of running directly")

    args = parser.parse_args()

    if args.bid_no:
        print(f"[*] Starting on-demand scrape for bid: {args.bid_no}")
        if args.enqueue:
            res = scrape_single_bid.delay(args.bid_no)
            print(f"[+] Task enqueued to Celery scraping_queue! Task ID: {res.id}")
        else:
            res = scrape_single_bid(args.bid_no)
            print(f"[+] Direct scrape result: {res}")
    else:
        print(f"[*] Starting crawl for category: '{args.bid_type}' (Target: {args.target})")
        if args.enqueue:
            res = scrape_category.delay(bid_type=args.bid_type, target_count=args.target)
            print(f"[+] Task enqueued to Celery scraping_queue! Task ID: {res.id}")
        else:
            res = scrape_category(bid_type=args.bid_type, target_count=args.target)
            print(f"[+] Direct crawl result: {res}")

