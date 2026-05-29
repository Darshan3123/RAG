# =========================================================
# pipeline/scraper.py
# Orchestrates one complete scraping run across all bid types
# =========================================================
import time
from config.settings import (
    BID_TYPES, TARGET_PER_TYPE, MAX_EMPTY_PAGES
)
from core.browser import GemBrowser
from core.parser import (
    extract_pdf_text, parse_bid_data,
    get_ra_from_card, get_product_type_from_card,
    get_dates_from_card,
    clean_text,
)
from storage.database import BidDatabase
from utils.antibot import sleep_between_cards
from utils.logger import get_logger

log = get_logger("scraper")


# =========================================================
# SCRAPE ONE BID TYPE
# =========================================================
def scrape_bid_type(
    browser: GemBrowser,
    db: BidDatabase,
    bid_type_name: str,
    seen_urls: set,
) -> dict:
    """
    Scrapes one bid type filter.
    Returns stats dict: {scraped, new, errors}
    """
    stats = {"scraped": 0, "new": 0, "errors": 0}
    collected  = 0
    page_num   = 1
    empty_pages = 0
    t_start    = time.time()

    log.info(f"{'='*50}")
    log.info(f"BID TYPE: {bid_type_name}")
    log.info(f"{'='*50}")

    # -- select filter --
    try:
        browser.reset_filters()
        browser.select_bid_type(bid_type_name)
        browser.select_ongoing_bids()  # Only scrape ACTIVE bids
    except Exception as e:
        log.error(f"Filter error for '{bid_type_name}': {e}")
        return stats

    # -- page loop --
    while collected < TARGET_PER_TYPE:
        log.info(
            f"  Page {page_num} | "
            f"Collected {collected}/{TARGET_PER_TYPE}"
        )
        cards       = browser.get_cards()
        total_cards = cards.count()
        log.info(f"  Cards found: {total_cards}")

        before = collected

        if total_cards == 0:
            empty_pages += 1
        else:
            # -- card loop --
            for i in range(total_cards):
                if collected >= TARGET_PER_TYPE:
                    break
                try:
                    card = cards.nth(i)

                    # extract RA + product type + DATES from card HTML
                    ra_no        = get_ra_from_card(card)
                    product_type = get_product_type_from_card(
                        card, bid_type_name
                    )
                    # FIX: scrape dates from card HTML (not PDF)
                    card_start, card_end = get_dates_from_card(card)

                    # extract links
                    doc_url, corr_url = (
                        browser.extract_card_links(card)
                    )

                    if not doc_url:
                        continue
                    if doc_url in seen_urls:
                        continue
                    seen_urls.add(doc_url)

                    # download PDF
                    pdf_path = browser.download_pdf(doc_url)
                    if not pdf_path:
                        log.warning(
                            f"  Skipping — download failed: {doc_url}"
                        )
                        stats["errors"] += 1
                        continue

                    # extract + parse text
                    pdf_text = extract_pdf_text(pdf_path)
                    if len(pdf_text.strip()) < 50:
                        log.warning("  Skipping — empty PDF text")
                        continue

                    parsed = parse_bid_data(pdf_text)

                    # build final record
                    bid = {
                        "bid_type":        bid_type_name,
                        "product_type":    product_type,
                        "bid_no":          parsed.get("bid_no", ""),
                        "ra_no":           ra_no,
                        "full_item_name":  parsed.get("full_item_name", ""),
                        "quantity":        parsed.get("quantity", ""),
                        "department":      parsed.get("department", ""),
                        # Use card dates (accurate) over PDF dates (unreliable)
                        "start_date":      card_start or parsed.get("start_date", ""),
                        "end_date":        card_end   or parsed.get("end_date", ""),
                        "estimated_value": parsed.get("estimated_value", ""),
                        "bid_packet_type": parsed.get("bid_packet_type", ""),
                        "document_url":    doc_url,
                        "corrigendum_url": corr_url,
                        "full_pdf_text":   clean_text(pdf_text),
                    }

                    # save to DB (returns True if NEW)
                    is_new = db.upsert(bid)
                    if is_new:
                        stats["new"] += 1

                    collected += 1
                    stats["scraped"] += 1

                    log.info(
                        f"  [{collected}/{TARGET_PER_TYPE}] "
                        f"{bid['bid_no']} | "
                        f"Type: {product_type} | "
                        f"RA: {ra_no or 'N/A'} | "
                        f"{'NEW' if is_new else 'seen'}"
                    )
                    sleep_between_cards()

                except Exception as e:
                    log.error(f"  Card {i} error: {e}")
                    stats["errors"] += 1

        # -- empty page tracking --
        if collected == before:
            empty_pages += 1
            log.info(
                f"  No new bids on page. "
                f"Empty streak: {empty_pages}/{MAX_EMPTY_PAGES}"
            )
        else:
            empty_pages = 0

        if empty_pages >= MAX_EMPTY_PAGES:
            log.info(
                f"  Stopping '{bid_type_name}' — "
                f"{MAX_EMPTY_PAGES} empty pages reached"
            )
            break

        # -- next page --
        if not browser.go_next_page():
            log.info("  No more pages.")
            break
        page_num += 1

    duration = round(time.time() - t_start, 2)
    db.log_run(
        bid_type_name,
        stats["scraped"],
        stats["new"],
        stats["errors"],
        duration,
    )
    log.info(
        f"  DONE '{bid_type_name}': "
        f"scraped={stats['scraped']} | "
        f"new={stats['new']} | "
        f"errors={stats['errors']} | "
        f"{duration}s"
    )
    return stats


# =========================================================
# FULL SCRAPE RUN  (called by scheduler every hour)
# =========================================================
def run_full_scrape(db: BidDatabase) -> dict:
    """
    Opens one browser session, iterates all bid types,
    saves to DB, exports JSON, returns summary stats.
    """
    run_stats = {
        "total_scraped": 0,
        "total_new":     0,
        "total_errors":  0,
        "by_type":       {},
    }
    seen_urls = set()          # dedup within this run

    log.info("")
    log.info("=" * 60)
    log.info("FULL SCRAPE RUN STARTED")
    log.info("=" * 60)

    try:
        with GemBrowser() as browser:
            browser.open_gem()

            for bid_type in BID_TYPES:
                try:
                    type_stats = scrape_bid_type(
                        browser, db, bid_type, seen_urls
                    )
                    run_stats["total_scraped"] += type_stats["scraped"]
                    run_stats["total_new"]     += type_stats["new"]
                    run_stats["total_errors"]  += type_stats["errors"]
                    run_stats["by_type"][bid_type] = type_stats
                except Exception as e:
                    log.error(
                        f"Fatal error on bid type "
                        f"'{bid_type}': {e}"
                    )

    except Exception as e:
        log.critical(f"Browser session failed: {e}")

    # export fresh JSON after every run
    db.export_json()

    db_stats = db.stats()
    log.info("")
    log.info("=" * 60)
    log.info(
        f"RUN COMPLETE | "
        f"Scraped: {run_stats['total_scraped']} | "
        f"New: {run_stats['total_new']} | "
        f"Errors: {run_stats['total_errors']} | "
        f"Total in DB: {db_stats['total']}"
    )
    log.info("=" * 60)

    return run_stats