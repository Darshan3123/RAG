# =========================================================
# pipeline/scraper.py
# Complete GeM Portal Web Scraper & Mineru VLM Integration
# =========================================================
"""
GeM Portal Document Scraping & Mineru VLM Pipeline Module.

Orchestrates multi-page Playwright browser interactions, HTML card parsing, PDF downloads
(Bid & RA documents), high-accuracy Mineru VLM document conversion into Markdown, field extraction,
JSON artifact assembly, SQLite persistence, and vector store indexing.
All 4 output files (.html, .pdf, .md, .json) are saved inside downloads/<Bid_No>/ subfolders.
"""

import os
import sys
import time
import json
import shutil
import asyncio
import threading
import multiprocessing
from pathlib import Path
from contextlib import contextmanager

# Suppress noisy lower-level library logging output
os.environ["MINERU_LOG_LEVEL"] = "WARNING"
os.environ["VLLM_LOGGING_LEVEL"] = "WARNING"

from Mineru_Document_To_Markdown import (
    async_convert_document,
    set_vlm_config,
    async_start_vllm_server,
    close_vllm_server,
)
from config.settings import (
    BID_TYPES, TARGET_PER_TYPE, MAX_EMPTY_PAGES, DOWNLOAD_DIR
)
from core.browser import GemBrowser
from core.parser import (
    get_card_details,
    parse_bid_data,
    clean_text,
)
from storage.database import BidDatabase
from utils.antibot import sleep_between_cards
from utils.logger import get_logger
from utils.pdf_hyperlinks import extract_hyperlinks, inject_hyperlinks_into_markdown

log = get_logger("scraper")


# ---------------------------------------------------------------------------
# CLI SPINNER & PROGRESS TIMING HELPERS
# ---------------------------------------------------------------------------
def _run_spinner(description: str, stop_event: multiprocessing.Event):
    """
    Run an animated CLI spinner in a separate multiprocessing process
    to prevent GIL or PyTorch subprocess locking during long CPU/GPU operations.
    
    Args:
        description (str): Text label to display alongside the spinner animation.
        stop_event (multiprocessing.Event): Event flag triggering spinner termination.
    """
    start_time = time.time()
    spinner = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    idx = 0
    while not stop_event.is_set():
        elapsed = time.time() - start_time
        sys.stdout.write(f"\r{spinner[idx]} {description} | Elapsed time: {elapsed:.1f}s")
        sys.stdout.flush()
        idx = (idx + 1) % len(spinner)
        time.sleep(0.1)


class ProgressTimer:
    """
    Multiprocessing background timer displaying animated CLI spinner and elapsed timing.
    
    Attributes:
        description (str): Status label describing the active operation.
    """
    def __init__(self, description: str):
        self.description = description
        self._stop_event = multiprocessing.Event()
        self._process = None
        self.start_time = None

    def start(self):
        """Start the background spinner process."""
        self.start_time = time.time()
        self._process = multiprocessing.Process(
            target=_run_spinner,
            args=(self.description, self._stop_event)
        )
        self._process.start()

    def stop(self):
        """Stop the background spinner process and print completion confirmation."""
        self._stop_event.set()
        if self._process:
            self._process.join()
        elapsed = time.time() - self.start_time
        sys.stdout.write(f"\r✅ {self.description} | Completed in {elapsed:.1f}s" + " " * 15 + "\n")
        sys.stdout.flush()


@contextmanager
def suppress_stdout_stderr():
    """
    Context manager that suppresses stdout and stderr at file-descriptor level (1 & 2)
    to keep CLI console output clean during noisy VLM model warmups and sub-process calls.
    """
    devnull = os.open(os.devnull, os.O_RDWR)
    old_stdout = os.dup(1)
    old_stderr = os.dup(2)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)
    try:
        yield
    finally:
        os.dup2(old_stdout, 1)
        os.dup2(old_stderr, 2)
        os.close(old_stdout)
        os.close(old_stderr)


class AsyncWorker:
    """
    Dedicated background thread holding a persistent asyncio event loop.
    Enables synchronous caller functions to safely run async Mineru routines
    without event loop conflicts or scope issues.
    """
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        """Worker thread entrypoint establishing the event loop."""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coro):
        """
        Execute an asynchronous coroutine synchronously in the worker event loop.
        
        Args:
            coro: Coroutine object to execute.
            
        Returns:
            Any: Result value returned by the coroutine.
        """
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()

    def run_sync(self, func, *args, **kwargs):
        """
        Wrap and execute a synchronous callable inside the worker loop context safely.
        """
        async def _wrapper():
            return func(*args, **kwargs)
        return self.run(_wrapper())

    def stop(self):
        """Cancel pending tasks and terminate the event loop thread cleanly."""
        def _cleanup():
            try:
                current_task = asyncio.current_task(self.loop)
                tasks = [t for t in asyncio.all_tasks(self.loop) if t is not current_task and not t.done()]
                for task in tasks:
                    task.cancel()
            except Exception:
                pass
            self.loop.stop()

        self.loop.call_soon_threadsafe(_cleanup)
        self.thread.join(timeout=5)
        if not self.loop.is_closed():
            try:
                self.loop.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# CARD PROCESSING & DATA ASSEMBLY
# ---------------------------------------------------------------------------
def process_card_item(
    card,
    browser: GemBrowser,
    db: BidDatabase,
    worker: AsyncWorker,
    bid_type_name: str,
    base_download_dir: str = DOWNLOAD_DIR
) -> dict:
    """
    Process a single Playwright bid card DOM element:
    1. Extract card metadata (full item name, quantities, departments, dates).
    2. Extract document links (Bid PDF, RA PDF, Corrigendum).
    3. Create subfolder named after Bid No inside DOWNLOAD_DIR: downloads/{safe_bid_no}/
    4. Download PDF files (Bid PDF and optional RA PDF) directly into the bid subfolder.
    5. Extract hyperlinks from the downloaded PDF using PyMuPDF.
    6. Convert Bid PDF to Markdown via Mineru VLM engine in Zero Save Mode (output_dir=None).
    7. Inject extracted hyperlinks as a section into the Markdown for RAG enrichment.
    8. Parse Markdown into structured schema using core parser.
    9. Save all 4 output artifacts (.html, .pdf, .md, .json) inside downloads/{safe_bid_no}/.
    10. Upsert record into SQLite database & ChromaDB vector store.
    
    Args:
        card: Playwright Locator pointing to bid card node.
        browser (GemBrowser): Active Playwright browser manager instance.
        db (BidDatabase): Active database interface object.
        worker (AsyncWorker): Background async worker for Mineru VLM invocation.
        bid_type_name (str): Selected category string label.
        base_download_dir (str): Base output directory path for downloads (defaults to DOWNLOAD_DIR).
        
    Returns:
        dict: Status report dictionary containing operation status, bid_no, and metadata.
    """
    # 1. Extract HTML Card Details
    card_data = get_card_details(card, bid_type_name)
    doc_url, ra_url, corr_url = browser.extract_card_links(card)

    if not doc_url:
        return {"status": "skipped_no_url"}

    if "card" in card_data:
        card_data["card"]["bid_pdf_url"] = doc_url
        card_data["card"]["ra_pdf_url"] = ra_url

    bid_no_raw = card_data.get("bid", {}).get("bid_no", "")
    safe_bid_no = (bid_no_raw or "unknown_bid").replace('/', '_')

    # Create dedicated subfolder inside downloads named after Bid No
    bid_dir = os.path.join(base_download_dir, safe_bid_no)
    os.makedirs(bid_dir, exist_ok=True)

    # 2. Save HTML Card Artifact inside downloads/<Bid_No>/
    card_html_path = os.path.join(bid_dir, f"{safe_bid_no}.html")
    try:
        with open(card_html_path, "w", encoding="utf-8") as f:
            f.write(card.inner_html())
    except Exception as e:
        log.warning(f"Could not save card HTML for {safe_bid_no}: {e}")

    # 3. Download Main Bid PDF Document directly into downloads/<Bid_No>/
    pdf_path = browser.download_pdf(
        document_url=doc_url,
        save_dir=bid_dir,
        filename=f"{safe_bid_no}.pdf"
    )
    if not pdf_path or not os.path.exists(pdf_path):
        log.warning(f"Download failed for doc_url: {doc_url}")
        return {"status": "error_download"}

    # 4. Download Reverse Auction (RA) PDF into downloads/<Bid_No>/ if available
    if ra_url:
        browser.download_pdf(
            document_url=ra_url,
            save_dir=bid_dir,
            filename=f"{safe_bid_no}_RA.pdf"
        )

    # 5. Extract hyperlinks from the Bid PDF using PyMuPDF
    #    Done before Mineru conversion so links can be injected into the Markdown.
    bid_hyperlinks: list[dict] = []
    try:
        bid_hyperlinks = extract_hyperlinks(pdf_path, source="bid")
        log.info(f"Hyperlinks extracted for {safe_bid_no}: {len(bid_hyperlinks)} links")
    except Exception as e:
        log.warning(f"Hyperlink extraction failed for {safe_bid_no}: {e}")

    # Also extract from RA PDF if it was downloaded
    ra_pdf_path = os.path.join(bid_dir, f"{safe_bid_no}_RA.pdf")
    if ra_url and os.path.exists(ra_pdf_path):
        try:
            ra_links = extract_hyperlinks(ra_pdf_path, source="ra")
            bid_hyperlinks.extend(ra_links)
            log.info(f"RA hyperlinks extracted for {safe_bid_no}: {len(ra_links)} links")
        except Exception as e:
            log.warning(f"RA hyperlink extraction failed for {safe_bid_no}: {e}")

    # 6. Execute Mineru VLM Engine Markdown Conversion (Zero Save Mode: output_dir=None)
    pdf_text = ""
    parsed_pdf_data = {}
    conv_timer = ProgressTimer(f"Converting PDF ({safe_bid_no}) to Markdown Via Mineru VLLM Server")
    conv_timer.start()
    try:
        with suppress_stdout_stderr():
            conv_result = worker.run(
                async_convert_document(
                    input_path=pdf_path,
                    output_dir=None,
                    backend="vlm-engine",
                    formula_enable=True,
                    table_enable=True,
                )
            )
            if isinstance(conv_result, dict):
                pdf_text = conv_result.get("markdown", "")
    except Exception as e:
        log.error(f"Mineru VLM conversion failed for {safe_bid_no}: {e}")
    finally:
        conv_timer.stop()

    if not pdf_text:
        log.warning(f"Mineru markdown result empty for {safe_bid_no}")

    # 7. Inject hyperlinks into Markdown for RAG text enrichment
    #    URLs become searchable via BM25 / dense retrieval in addition to
    #    being stored in the structured hyperlinks[] JSON field.
    if pdf_text and bid_hyperlinks:
        pdf_text = inject_hyperlinks_into_markdown(pdf_text, bid_hyperlinks)

    # 8. Parse PDF Markdown into Structured Data Schema
    product_type = card_data.get("bid", {}).get("product_type", "PRODUCT")
    if pdf_text.strip():
        parsed_pdf_data = parse_bid_data(pdf_text, product_type)
        card_data["bid"]["process_kind"] = parsed_pdf_data.pop("process_kind", "")
        card_data["bid"]["base_type"] = parsed_pdf_data.pop("base_type", "")

        # Overwrite card.departments with the richer PDF-extracted values
        # (Ministry/State, Department, Organisation, Office) which are far
        # more reliable than what can be scraped from the card HTML.
        pdf_depts = parsed_pdf_data.get("departments", {})
        if any(pdf_depts.values()):
            card_data["card"]["departments"] = [{
                "ministry_state_name": pdf_depts.get("ministry_state_name", ""),
                "department_name":     pdf_depts.get("department_name", ""),
                "organisation_name":   pdf_depts.get("organisation_name", ""),
                "office_name":         pdf_depts.get("office_name", ""),
            }]

        # Save Markdown File Artifact inside downloads/<Bid_No>/
        pdf_md_path = os.path.join(bid_dir, f"{safe_bid_no}.md")
        try:
            with open(pdf_md_path, "w", encoding="utf-8-sig") as f:
                f.write(pdf_text)
        except Exception as e:
            log.warning(f"Could not save Markdown for {safe_bid_no}: {e}")

    # 9. Assemble Final Unified JSON Schema Artifact inside downloads/<Bid_No>/
    #    hyperlinks[] is a top-level sibling of 'pdf', matching the schema
    #    already observed in scraped bids (e.g. GEM_2026_B_7495766).
    final_bid = {
        "_id": safe_bid_no,
        "bid": card_data.get("bid", {}),
        "card": card_data.get("card", {}),
        "pdf": parsed_pdf_data,
        "hyperlinks": bid_hyperlinks,          # ← all URI links extracted from the PDF
        "normalized": {},
        "validation": {"issues": []},
        "full_pdf_text": pdf_text,
    }
    json_path = os.path.join(bid_dir, f"{safe_bid_no}.json")
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(final_bid, f, indent=4, ensure_ascii=False)
    except Exception as e:
        log.warning(f"Could not save JSON for {safe_bid_no}: {e}")

    # 10. Upsert Record into SQLite & ChromaDB Vector Store
    card_items = card_data.get("card", {}).get("items", [])
    item_name = card_items[0].get("name", "") if card_items else ""
    qty_val = str(card_items[0].get("quantity", "")) if card_items else ""

    card_depts = card_data.get("card", {}).get("departments", [])
    dept_name = card_depts[0].get("name", "") if card_depts else ""

    bid_packet_type_val = ""
    bt_data = parsed_pdf_data.get("bid_type")
    if isinstance(bt_data, dict):
        bid_packet_type_val = bt_data.get("type_of_bid", "")
    elif isinstance(bt_data, str):
        bid_packet_type_val = bt_data

    db_record = {
        "document_url":    str(doc_url or ""),
        "bid_no":          str(bid_no_raw or safe_bid_no or ""),
        "ra_no":           str(card_data.get("bid", {}).get("ra_no", "") or ""),
        "bid_type":        str(bid_type_name or ""),
        "product_type":    str(product_type or ""),
        "full_item_name":  str(item_name or ""),
        "quantity":        str(qty_val or ""),
        "department":      str(dept_name or ""),
        "start_date":      str(card_data.get("card", {}).get("start_datetime", "") or ""),
        "end_date":        str(card_data.get("card", {}).get("end_datetime", "") or ""),
        "estimated_value": str(parsed_pdf_data.get("financials", {}).get("estimated_value") or ""),
        "bid_packet_type": str(bid_packet_type_val or ""),
        "corrigendum_url": str(corr_url or ""),
        "full_pdf_text":   clean_text(pdf_text),
    }

    embed_timer = ProgressTimer(f"Embedding & indexing vectors ({safe_bid_no})")
    embed_timer.start()
    try:
        is_new = db.upsert(db_record)
    finally:
        embed_timer.stop()

    return {"status": "success", "is_new": is_new, "bid_no": safe_bid_no, "item": item_name, "dir": bid_dir}


# ---------------------------------------------------------------------------
# CATEGORY & SINGLE-BID SCRAPING RUNNERS
# ---------------------------------------------------------------------------
def scrape_bid_type(
    browser: GemBrowser,
    db: BidDatabase,
    worker: AsyncWorker,
    bid_type_name: str,
    seen_urls: set,
) -> dict:
    """
    Iterate over pagination for a specific bid category (e.g. Product Bid/RAs)
    up to TARGET_PER_TYPE records.
    
    Args:
        browser (GemBrowser): Active Playwright browser session.
        db (BidDatabase): SQLite database connection instance.
        worker (AsyncWorker): Async background worker for Mineru conversion.
        bid_type_name (str): Label of selected bid category.
        seen_urls (set): Set tracking URLs already processed in current run.
        
    Returns:
        dict: Execution statistics breakdown (scraped, new, errors).
    """
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
                    doc_url, _, _ = browser.extract_card_links(card)
                    if not doc_url or doc_url in seen_urls:
                        continue
                    seen_urls.add(doc_url)

                    res = process_card_item(
                        card=card,
                        browser=browser,
                        db=db,
                        worker=worker,
                        bid_type_name=bid_type_name,
                    )

                    if res.get("status") == "success":
                        collected += 1
                        stats["scraped"] += 1
                        if res.get("is_new"):
                            stats["new"] += 1
                        log.info(
                            f"  [{collected}/{TARGET_PER_TYPE}] {res['bid_no']} | "
                            f"Item: {res['item'][:40]} | {'NEW' if res.get('is_new') else 'seen'}"
                        )
                        sleep_between_cards()
                    elif res.get("status") == "error_download":
                        stats["errors"] += 1

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
        f"  DONE '{bid_type_name}': scraped={stats['scraped']} | new={stats['new']} | "
        f"errors={stats['errors']} | {duration}s"
    )
    return stats


def scrape_specific_bid(db: BidDatabase, bid_no: str) -> dict:
    """
    Targeted search and extraction routine for a single specific Bid / RA number
    via GeM portal Advanced Search interface.
    
    Args:
        db (BidDatabase): SQLite database interface.
        bid_no (str): Target bid number string (e.g. 'GEM/2026/B/7768206').
        
    Returns:
        dict: Result status dictionary returned by `process_card_item`.
    """
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    worker = AsyncWorker()
    # RTX 2050 (4 GB VRAM) tuning:
    #   max_gpu_util=0.78  → requests ~3.12 GB, fits within the ~3.22 GB
    #                        actually free at startup (display driver holds
    #                        ~780 MB on WSL2, leaving <3.8 GB available)
    #   model_len=4096     → 4K context for longer PDFs; pushes KV cache
    #                        but still fits in 4GB with batch_size=16
    #   batch_size=16      → higher throughput for multi-page PDFs; vLLM
    #                        will auto-adjust if it exceeds available memory
    set_vlm_config(batch_size=16, max_gpu_util=0.78, model_len=4096)

    server_timer = ProgressTimer("Starting Mineru vLLM server")
    server_timer.start()
    try:
        with suppress_stdout_stderr():
            worker.run(async_start_vllm_server())
    finally:
        server_timer.stop()

    try:
        log.info(f"Starting browser for specific bid search: {bid_no}")
        with GemBrowser() as browser:
            browser.advanced_search_bid(bid_no)
            browser.wait_for_cards()
            cards = browser.get_cards()
            total = cards.count()

            if total == 0:
                log.warning(f"No cards found for Bid: {bid_no}")
                return {"status": "not_found"}

            log.info(f"Found {total} card(s) matching search.")
            card = cards.nth(0)
            res = process_card_item(
                card=card,
                browser=browser,
                db=db,
                worker=worker,
                bid_type_name="Product Bid/RAs",
            )
            return res
    finally:
        close_timer = ProgressTimer("Closing Mineru vLLM server")
        close_timer.start()
        try:
            with suppress_stdout_stderr():
                worker.run_sync(close_vllm_server)
        except Exception:
            pass
        finally:
            close_timer.stop()
        worker.stop()


def run_full_scrape(db: BidDatabase) -> dict:
    """
    Full automated scraping run entrypoint:
    Pre-warms Mineru vLLM server, launches stealth Playwright browser context,
    scrapes all target bid types, saves raw artifacts and updates database and JSON export.
    
    Args:
        db (BidDatabase): Active database interface object.
        
    Returns:
        dict: Overall execution metrics summary dict.
    """
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    run_stats = {
        "total_scraped": 0,
        "total_new":     0,
        "total_errors":  0,
        "by_type":       {},
    }
    seen_urls = set()

    log.info("")
    log.info("=" * 60)
    log.info("FULL SCRAPE RUN STARTED (MINERU VLM PARSER)")
    log.info("=" * 60)

    worker = AsyncWorker()
    # RTX 2050 (4 GB VRAM) tuning — see scrape_specific_bid for rationale
    set_vlm_config(batch_size=16, max_gpu_util=0.78, model_len=4096)

    server_timer = ProgressTimer("Starting Mineru vLLM server")
    server_timer.start()
    try:
        with suppress_stdout_stderr():
            worker.run(async_start_vllm_server())
    finally:
        server_timer.stop()

    try:
        with GemBrowser() as browser:
            browser.open_gem()
            for bid_type in BID_TYPES:
                try:
                    type_stats = scrape_bid_type(
                        browser=browser,
                        db=db,
                        worker=worker,
                        bid_type_name=bid_type,
                        seen_urls=seen_urls,
                    )
                    run_stats["total_scraped"] += type_stats["scraped"]
                    run_stats["total_new"]     += type_stats["new"]
                    run_stats["total_errors"]  += type_stats["errors"]
                    run_stats["by_type"][bid_type] = type_stats
                except Exception as e:
                    log.error(f"Fatal error on bid type '{bid_type}': {e}")
    except Exception as e:
        log.critical(f"Browser session failed: {e}")
    finally:
        close_timer = ProgressTimer("Closing Mineru vLLM server")
        close_timer.start()
        try:
            with suppress_stdout_stderr():
                worker.run_sync(close_vllm_server)
        except Exception:
            pass
        finally:
            close_timer.stop()
        worker.stop()

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