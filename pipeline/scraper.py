# =========================================================
# pipeline/scraper.py
# Orchestrates one complete scraping run across all bid types
#
# IMPROVEMENT (this revision):
#   - Item name / quantity / department / dates are now read
#     STRAIGHT FROM THE CARD HTML (popover `data-content`),
#     so they are no longer truncated like
#       "Onion , Potato , Tomato , Cabbage , Cauliflower ,"
#   - PDF parsing is kept ONLY as a fallback and for fields
#     the card does not expose (estimated_value, bid_packet_type).
# =========================================================
import time
from config.settings import (
    BID_TYPES, TARGET_PER_TYPE, MAX_EMPTY_PAGES
)
from core.browser import GemBrowser
from core.parser import (
    extract_pdf_text, parse_bid_data, parse_bid_extended,
    assemble_tender_record,
    get_card_details,
    clean_text,
)
from storage.database import BidDatabase
from utils.antibot import sleep_between_cards
from utils.logger import get_logger

log = get_logger("scraper")


def _pick(card_val: str, pdf_val: str) -> str:
    """Prefer card value (untruncated, accurate); fall back to PDF."""
    cv = (card_val or "").strip()
    pv = (pdf_val or "").strip()
    if cv:
        # If both available, take whichever is longer (more complete)
        if pv and len(pv) > len(cv) * 1.5:
            return pv
        return cv
    return pv


# =========================================================
# SCRAPE ONE BID TYPE
# =========================================================
def scrape_bid_type(
    browser: GemBrowser,
    db: BidDatabase,
    bid_type_name: str,
    seen_urls: set,
) -> dict:
    stats = {"scraped": 0, "new": 0, "errors": 0}
    collected = 0
    page_num = 1
    empty_pages = 0
    t_start = time.time()

    log.info(f"{'=' * 50}")
    log.info(f"BID TYPE: {bid_type_name}")
    log.info(f"{'=' * 50}")

    try:
        browser.reset_filters()
        browser.select_bid_type(bid_type_name)
        browser.select_ongoing_bids()
    except Exception as e:
        log.error(f"Filter error for '{bid_type_name}': {e}")
        return stats

    while collected < TARGET_PER_TYPE:
        log.info(f"  Page {page_num} | Collected {collected}/{TARGET_PER_TYPE}")

        # Make sure all cards are rendered before reading them
        browser.wait_for_cards()

        cards = browser.get_cards()
        total_cards = cards.count()
        log.info(f"  Cards found: {total_cards}")

        before = collected

        if total_cards == 0:
            empty_pages += 1
        else:
            for i in range(total_cards):
                if collected >= TARGET_PER_TYPE:
                    break
                try:
                    card = cards.nth(i)

                    # ── 1. PULL EVERY POSSIBLE FIELD FROM CARD HTML ──
                    log.info(f"  Card {i+1}/{total_cards}: reading card details...")
                    card_data = get_card_details(card, bid_type_name)
                    log.info(f"  Card {i+1}: bid_no={card_data['bid_no']}")

                    log.info(f"  Card {i+1}: extracting links...")
                    doc_url, corr_url = browser.extract_card_links(card)
                    if not doc_url:
                        log.info(f"  Card {i+1}: no doc_url, skipping")
                        continue
                    if doc_url in seen_urls:
                        log.info(f"  Card {i+1}: already seen, skipping")
                        continue
                    seen_urls.add(doc_url)

                    # ── 2. DOWNLOAD + PARSE PDF (fallback fields) ──
                    log.info(f"  Card {i+1}: downloading PDF from {doc_url}...")
                    pdf_path = browser.download_pdf(doc_url)
                    if not pdf_path:
                        log.warning(f"  Skipping — download failed: {doc_url}")
                        stats["errors"] += 1
                        continue

                    log.info(f"  Card {i+1}: extracting PDF text...")
                    pdf_text = extract_pdf_text(pdf_path)
                    if len(pdf_text.strip()) < 50:
                        log.warning("  Skipping — empty PDF text")
                        continue

                    log.info(f"  Card {i+1}: parsing bid data...")
                    parsed = parse_bid_data(pdf_text)
                    extended = parse_bid_extended(pdf_text, pdf_path=pdf_path)

                    # ── 3. MERGE — prefer card data, then extended PDF data ──
                    bid = {
                        "bid_type":        bid_type_name,
                        "product_type":    card_data["product_type"],
                        "bid_no":          card_data["bid_no"] or parsed.get("bid_no", ""),
                        "ra_no":           card_data["ra_no"],
                        "full_item_name":  _pick(card_data["full_item_name"],
                                                 parsed.get("full_item_name", "")),
                        "quantity":        _pick(card_data["quantity"],
                                                 parsed.get("quantity", "")),
                        "department":      _pick(card_data["department"],
                                                 parsed.get("department", "")),
                        "start_date":      card_data["start_date"] or parsed.get("start_date", ""),
                        "end_date":        card_data["end_date"]   or parsed.get("end_date", ""),
                        # Fields only from PDF
                        "estimated_value": parsed.get("estimated_value", ""),
                        "bid_packet_type": parsed.get("bid_packet_type", ""),
                        "document_url":    doc_url,
                        "corrigendum_url": corr_url,
                        "full_pdf_text":   clean_text(pdf_text),
                        # Extended fields from new parser
                        "category":        extended.get("category", ""),
                        "sub_category":    extended.get("sub_category", ""),
                        "product_name":    extended.get("product_name", ""),
                        "procurement_type": extended.get("procurement_type", ""),
                        "authority":       extended.get("authority", "") or _pick(card_data["department"], parsed.get("department", "")),
                        "sector":          extended.get("sector", ""),
                        "earnest_amount":  extended.get("earnest_amount", ""),
                        "doc_cost":        extended.get("doc_cost", ""),
                        "open_date":       extended.get("open_date", ""),
                        "search_text":     extended.get("search_text", ""),
                        "is_corrigendum":  extended.get("is_corrigendum", False),
                        "address":         extended.get("address", ""),
                        "address_pin":     extended.get("address_pin", ""),
                        "city":            extended.get("city", ""),
                        "state":           extended.get("state", ""),
                        "contact_person":  extended.get("contact_person", ""),
                        "contact_email":   extended.get("contact_email", ""),
                        "contact_phone":   extended.get("contact_phone", ""),
                        "document_path":   extended.get("document_path", ""),
                    }

                    # ── 4. Build the unified tender-format record ──
                    log.info(f"  Card {i+1}: assembling tender record...")
                    page_url = getattr(browser, "current_url", "https://gem.gov.in/")
                    tender_record = assemble_tender_record(bid, page_url=page_url)

                    log.info(f"  Card {i+1}: saving to database...")
                    is_new = db.upsert(bid, tender_record=tender_record)
                    if is_new:
                        stats["new"] += 1
                    collected += 1
                    stats["scraped"] += 1

                    log.info(
                        f"  [{collected}/{TARGET_PER_TYPE}] "
                        f"{bid['bid_no']} | "
                        f"Item: {bid['full_item_name'][:50]}... | "
                        f"Qty: {bid['quantity'] or 'N/A'} | "
                        f"{'NEW' if is_new else 'seen'}"
                    )
                    sleep_between_cards()

                except Exception as e:
                    log.error(f"  Card {i} error: {e}")
                    stats["errors"] += 1

        if collected == before:
            empty_pages += 1
            log.info(f"  No new bids on page. Empty streak: {empty_pages}/{MAX_EMPTY_PAGES}")
        else:
            empty_pages = 0

        if empty_pages >= MAX_EMPTY_PAGES:
            log.info(f"  Stopping '{bid_type_name}' — {MAX_EMPTY_PAGES} empty pages reached")
            break

        if not browser.go_next_page():
            log.info("  No more pages.")
            break
        page_num += 1

    duration = round(time.time() - t_start, 2)
    db.log_run(bid_type_name, stats["scraped"], stats["new"], stats["errors"], duration)
    log.info(
        f"  DONE '{bid_type_name}': "
        f"scraped={stats['scraped']} | new={stats['new']} | "
        f"errors={stats['errors']} | {duration}s"
    )
    return stats


# =========================================================
# FULL SCRAPE RUN
# =========================================================
def run_full_scrape(db: BidDatabase) -> dict:
    run_stats = {
        "total_scraped": 0,
        "total_new":     0,
        "total_errors":  0,
        "by_type":       {},
    }
    seen_urls = set()

    log.info("")
    log.info("=" * 60)
    log.info("FULL SCRAPE RUN STARTED")
    log.info("=" * 60)

    try:
        with GemBrowser() as browser:
            browser.open_gem()
            for bid_type in BID_TYPES:
                try:
                    type_stats = scrape_bid_type(browser, db, bid_type, seen_urls)
                    run_stats["total_scraped"] += type_stats["scraped"]
                    run_stats["total_new"]     += type_stats["new"]
                    run_stats["total_errors"]  += type_stats["errors"]
                    run_stats["by_type"][bid_type] = type_stats
                except Exception as e:
                    log.error(f"Fatal error on bid type '{bid_type}': {e}")
    except Exception as e:
        log.critical(f"Browser session failed: {e}")

    db.export_json()

    db_stats = db.stats()
    log.info("")
    log.info("=" * 60)
    log.info(
        f"RUN COMPLETE | Scraped: {run_stats['total_scraped']} | "
        f"New: {run_stats['total_new']} | Errors: {run_stats['total_errors']} | "
        f"Total in DB: {db_stats['total']}"
    )
    log.info("=" * 60)
    return run_stats