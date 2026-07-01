# =========================================================
# scraper/pipeline/scraper.py
# Orchestrates one complete scraping run across all bid types.
# Saves bids to MongoDB (no RAG/embedding call here).
# =========================================================
import time
from shared.config.settings import BID_TYPES, TARGET_PER_TYPE, MAX_EMPTY_PAGES
from scraper.core.browser import GemBrowser
from scraper.core.parser import (
    extract_pdf_text, parse_bid_data, parse_bid_extended,
    assemble_tender_record, get_card_details, clean_text,
    extract_pdf_intelligence,
)
from scraper.core.validator import post_process_bid
from shared.storage import mongo_client as db
from shared.utils.antibot import sleep_between_cards
from shared.utils.logger import get_logger

log = get_logger("scraper")


def _pick(card_val: str, pdf_val: str) -> str:
    """Prefer card value (untruncated); fall back to PDF."""
    cv = (card_val or "").strip()
    pv = (pdf_val  or "").strip()
    if cv:
        if pv and len(pv) > len(cv) * 1.5:
            return pv
        return cv
    return pv


def _to_int(val) -> int | None:
    """Convert string/float quantity to int; returns None if unparseable."""
    if val is None or val == "":
        return None
    try:
        import re as _re
        return int(float(_re.sub(r"[,\s]", "", str(val))))
    except (ValueError, TypeError):
        return None


# =========================================================
# SCRAPE ONE BID TYPE
# =========================================================
def scrape_bid_type(
    browser: GemBrowser,
    bid_type_name: str,
    seen_urls: set,
) -> dict:
    stats = {"scraped": 0, "new": 0, "errors": 0}
    collected  = 0
    page_num   = 1
    empty_pages = 0
    t_start    = time.time()

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
        browser.wait_for_cards()
        cards       = browser.get_cards()
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
                    card      = cards.nth(i)
                    card_data = get_card_details(card, bid_type_name)
                    log.info(f"  Card {i+1}: bid_no={card_data['bid_no']}")

                    doc_url, corr_url, ra_url = browser.extract_card_links(card)
                    if not doc_url:
                        continue
                    if doc_url in seen_urls:
                        continue
                    seen_urls.add(doc_url)

                    pdf_path = browser.download_pdf(doc_url, bid_type=bid_type_name)
                    if not pdf_path:
                        stats["errors"] += 1
                        continue
                        
                    ra_pdf_path = None
                    if ra_url:
                        ra_pdf_path = browser.download_pdf(ra_url, bid_type=bid_type_name)

                    pdf_text = extract_pdf_text(pdf_path)
                    if len(pdf_text.strip()) < 50:
                        log.warning("  Skipping — empty PDF text")
                        continue
                        
                    ra_pdf_text = ""
                    if ra_pdf_path:
                        ra_pdf_text = extract_pdf_text(ra_pdf_path)

                    try:
                        parsed        = parse_bid_data(pdf_text)
                        extended      = parse_bid_extended(pdf_text, pdf_path=pdf_path)
                        pdf_intel     = extract_pdf_intelligence(pdf_text, card_data["product_type"])
                        
                        from scraper.core.parsers.ra_parser import parse_ra_intelligence
                        ra_pdf_intel = parse_ra_intelligence(ra_pdf_text) if ra_pdf_text else {}
                        pdf_intel["ra_pdf"] = ra_pdf_intel
                        
                    except Exception as parse_err:
                        log.error(f"  Card {i+1}: parse error — {parse_err}", exc_info=True)
                        stats["errors"] += 1
                        continue

                    bid = {
                        "bid_type":        bid_type_name,
                        "product_type":    card_data["product_type"],
                        "bid_no":          card_data["bid_no"] or parsed.get("bid_no", ""),
                        "ra_no":           card_data["ra_no"] or None,
                        "full_item_name":  _pick(card_data["full_item_name"],
                                                 parsed.get("full_item_name", "")),
                        "quantity":        _to_int(_pick(card_data["quantity"],
                                                 parsed.get("quantity", ""))),
                        "department":      _pick(card_data["department"],
                                                 parsed.get("department", "")),
                        "start_date":      card_data["start_date"] or parsed.get("start_date", ""),
                        "end_date":        card_data["end_date"]   or parsed.get("end_date", ""),
                        "estimated_value": parsed.get("estimated_value") or None,
                        "bid_packet_type": parsed.get("bid_packet_type") or None,
                        "document_url":    doc_url,
                        "corrigendum_url": corr_url or None,
                        "ra_document_url": ra_url or None,
                        "full_pdf_text":   clean_text(pdf_text),
                        "ra_full_pdf_text": clean_text(ra_pdf_text),
                        "category":        extended.get("category", ""),
                        "sub_category":    extended.get("sub_category", ""),
                        "product_name":    extended.get("product_name", ""),
                        "procurement_type": extended.get("procurement_type", ""),
                        "authority":       extended.get("authority", "") or _pick(
                                               card_data["department"], parsed.get("department", "")),
                        "sector":          extended.get("sector", ""),
                        "earnest_amount":  extended.get("earnest_amount", ""),
                        "doc_cost":        extended.get("doc_cost") or None,
                        "open_date":       extended.get("open_date", ""),
                        "search_text":     extended.get("search_text", ""),
                        "is_corrigendum":  extended.get("is_corrigendum", False),
                        "address":         extended.get("address", ""),
                        "address_pin":     extended.get("address_pin", ""),
                        "city":            extended.get("city", ""),
                        "state":           extended.get("state", ""),
                        "contact_person":  extended.get("contact_person", ""),
                        "contact_email":   extended.get("contact_email", "") or None,
                        "contact_phone":   extended.get("contact_phone", "") or None,
                        "document_path":   extended.get("document_path", ""),
                        "organization_name": extended.get("organization_name", ""),
                        "office_name":     extended.get("office_name", ""),
                        "pdf_intelligence": pdf_intel,
                    }

                    page_url      = getattr(browser, "current_url", "https://gem.gov.in/")

                    # ── Post-process: heuristic corrections before record assembly ──
                    bid, parse_issues = post_process_bid(bid)
                    if parse_issues:
                        bid["parse_issues"] = parse_issues

                    tender_record = assemble_tender_record(bid, page_url=page_url)

                    # ── Save to MongoDB (no RAG call) ──
                    is_new = db.upsert(tender_record)
                    if is_new:
                        stats["new"] += 1
                    collected    += 1
                    stats["scraped"] += 1

                    log.info(
                        f"  [{collected}/{TARGET_PER_TYPE}] "
                        f"{bid['bid_no']} | {bid['full_item_name'][:50]} | "
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
def run_full_scrape() -> dict:
    run_stats = {"total_scraped": 0, "total_new": 0, "total_errors": 0, "by_type": {}}
    seen_urls = set()

    log.info("=" * 60)
    log.info("FULL SCRAPE RUN STARTED")
    log.info("=" * 60)

    try:
        with GemBrowser() as browser:
            browser.open_gem()
            for bid_type in BID_TYPES:
                try:
                    type_stats = scrape_bid_type(browser, bid_type, seen_urls)
                    run_stats["total_scraped"] += type_stats["scraped"]
                    run_stats["total_new"]     += type_stats["new"]
                    run_stats["total_errors"]  += type_stats["errors"]
                    run_stats["by_type"][bid_type] = type_stats
                except Exception as e:
                    log.error(f"Fatal error on bid type '{bid_type}': {e}")
    except Exception as e:
        log.critical(f"Browser session failed: {e}")

    from shared.config.settings import JSON_OUT_PATH
    db.export_json(JSON_OUT_PATH)

    s = db.stats()
    log.info(
        f"RUN COMPLETE | Scraped: {run_stats['total_scraped']} | "
        f"New: {run_stats['total_new']} | Errors: {run_stats['total_errors']} | "
        f"Total in DB: {s['total']}"
    )
    return run_stats
