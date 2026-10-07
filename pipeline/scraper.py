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
import re
import time
import json
import shutil
import asyncio
import threading
import multiprocessing
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Dict, Any, List, Sequence

# Suppress noisy lower-level library logging output
os.environ["MINERU_LOG_LEVEL"] = "WARNING"
os.environ["VLLM_LOGGING_LEVEL"] = "WARNING"

try:
    from Mineru_Document_To_Markdown import (
        async_convert_document,
        set_vlm_config,
        async_start_vllm_server,
        close_vllm_server,
    )
except ImportError:
    async_convert_document = None
    set_vlm_config = None
    async_start_vllm_server = None
    close_vllm_server = None
from config.settings import (
    BID_TYPES, TARGET_PER_TYPE, MAX_EMPTY_PAGES, DOWNLOAD_DIR,
    MAX_RETRIES_PER_BID, RETRY_DELAY_SECONDS, ENABLE_ATC_ANALYSIS,
    OCR_PROVIDER, ENABLE_PDF_ATC_SPLIT
)
from core.ocr import DocumentOCRFactory, OCRResult, OCRUsage
from core.ocr.pricing import calculate_saved_cost
from core.pdf_splitter import (
    detect_atc_boundary,
    create_core_pdf_for_ocr,
    extract_atc_markdown_pymupdf,
    stitch_hybrid_markdown,
)
from core.browser import GemBrowser
from core.parser import (
    get_card_details,
    parse_bid_data,
    clean_text,
)
from core.normalizer import (
    normalize_bid_data,
    validate_bid_data,
)
from pipeline.atc_analyzer import analyze_bid_atc
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
    worker: Optional[AsyncWorker] = None,
    bid_type_name: str = "Product Bid/RAs",
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
        filename=f"{safe_bid_no}.pdf",
        retries=MAX_RETRIES_PER_BID
    )
    if not pdf_path or not os.path.exists(pdf_path):
        log.warning(f"Download failed for doc_url: {doc_url}")
        return {"status": "error_download"}

    # 4. Download Reverse Auction (RA) PDF into downloads/<Bid_No>/ if available
    if ra_url:
        browser.download_pdf(
            document_url=ra_url,
            save_dir=bid_dir,
            filename=f"{safe_bid_no}_RA.pdf",
            retries=MAX_RETRIES_PER_BID
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

    # 6. Execute Selective PDF Slicing & Pluggable Document OCR
    split_info = None
    target_ocr_pdf = pdf_path
    if ENABLE_PDF_ATC_SPLIT:
        try:
            split_info = detect_atc_boundary(pdf_path)
            if split_info and split_info.pages_saved > 0:
                sliced_pdf_path = os.path.join(bid_dir, f"{safe_bid_no}_core.pdf")
                target_ocr_pdf = create_core_pdf_for_ocr(
                    pdf_path=pdf_path,
                    pages_for_ocr=split_info.pages_for_ocr,
                    output_path=sliced_pdf_path
                )
                log.info(
                    f"Selective PDF Slicing active for {safe_bid_no}: "
                    f"Sending {split_info.pages_for_ocr}/{split_info.total_pages} pages to OCR "
                    f"(Saved {split_info.pages_saved} pages via PyMuPDF)"
                )
        except Exception as e:
            log.warning(f"Selective PDF slicing check failed for {safe_bid_no}: {e}")
            split_info = None
            target_ocr_pdf = pdf_path

    pdf_text = ""
    parsed_pdf_data = {}
    ocr_usage_data = {}

    conv_timer = ProgressTimer(f"Converting PDF ({safe_bid_no}) via [{OCR_PROVIDER.upper()}] OCR")
    conv_timer.start()
    try:
        if OCR_PROVIDER == "mineru":
            with suppress_stdout_stderr():
                if worker:
                    conv_result = worker.run(
                        async_convert_document(
                            input_path=target_ocr_pdf,
                            output_dir=None,
                            backend="vlm-engine",
                            formula_enable=True,
                            table_enable=True,
                        )
                    )
                    if isinstance(conv_result, dict):
                        pdf_text = conv_result.get("markdown", "")
        else:
            ocr_provider = DocumentOCRFactory.get_provider(OCR_PROVIDER)
            ocr_result = ocr_provider.convert_pdf_to_markdown(
                pdf_path=target_ocr_pdf,
                save_json=True,
                output_dir=bid_dir
            )
            pdf_text = ocr_result.markdown
            ocr_usage_data = ocr_result.usage.to_dict()

            # Record slicing savings telemetry if slicing was applied
            if split_info and split_info.pages_saved > 0:
                savings = calculate_saved_cost(
                    provider=ocr_result.provider,
                    model=ocr_result.model,
                    pages_saved=split_info.pages_saved
                )
                ocr_usage_data["total_pdf_pages"] = split_info.total_pages
                ocr_usage_data["pages_for_ocr"] = split_info.pages_for_ocr
                ocr_usage_data["pages_saved_by_slicing"] = split_info.pages_saved
                ocr_usage_data["estimated_savings_usd"] = savings["saved_usd"]
                ocr_usage_data["estimated_savings_inr"] = savings["saved_inr"]

            savings_str = (
                f" [Saved: ${ocr_usage_data.get('estimated_savings_usd', 0):.4f} (₹{ocr_usage_data.get('estimated_savings_inr', 0):.2f})]"
                if split_info and split_info.pages_saved > 0 else ""
            )
            log.info(
                f"OCR [{ocr_result.provider.upper()}] completed for {safe_bid_no}: "
                f"{ocr_result.usage.pages_processed} pages, {ocr_result.usage.latency_seconds:.1f}s, "
                f"Cost: ${ocr_result.usage.estimated_cost_usd:.4f} (₹{ocr_result.usage.estimated_cost_inr:.2f}){savings_str}"
            )
    except Exception as e:
        log.error(f"Document OCR conversion failed for {safe_bid_no} using {OCR_PROVIDER}: {e}")
    finally:
        conv_timer.stop()

    # If sliced, stitch the PyMuPDF ATC markdown onto the OCR markdown
    if split_info and split_info.pages_saved > 0 and pdf_text:
        try:
            atc_pymupdf_md = extract_atc_markdown_pymupdf(
                pdf_path=pdf_path,
                split_page_index=split_info.split_page_index,
                heading_y0=split_info.heading_y0
            )
            pdf_text = stitch_hybrid_markdown(pdf_text, atc_pymupdf_md)
            log.info(
                f"Stitched PyMuPDF ATC markdown into {safe_bid_no} "
                f"({len(atc_pymupdf_md)} chars added)"
            )
        except Exception as e:
            log.warning(f"Error stitching PyMuPDF ATC text for {safe_bid_no}: {e}")

    if not pdf_text:
        log.warning(f"OCR markdown result empty for {safe_bid_no}")

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

        # Enrich card.items if detailed PDF items exist
        pdf_items = parsed_pdf_data.get("items", {})
        detailed_items = []
        if pdf_items and isinstance(pdf_items, dict):
            for k, v in pdf_items.items():
                if re.match(r"^item \d+$", k, re.IGNORECASE) and isinstance(v, dict):
                    cat = v.get("item_category", "").strip()
                    q = v.get("quantity")
                    if cat:
                        detailed_items.append({"name": cat, "quantity": q if q is not None else 0})
        if detailed_items:
            card_data["card"]["items"] = detailed_items

        # Save Markdown File Artifact inside downloads/<Bid_No>/
        pdf_md_path = os.path.join(bid_dir, f"{safe_bid_no}.md")
        try:
            with open(pdf_md_path, "w", encoding="utf-8-sig") as f:
                f.write(pdf_text)
        except Exception as e:
            log.warning(f"Could not save Markdown for {safe_bid_no}: {e}")

    # 9. Normalize & Validate Bid Data
    normalized_data = normalize_bid_data(card_data, parsed_pdf_data, pdf_text)
    validation_data = validate_bid_data(
        bid_no=safe_bid_no,
        card_data=card_data,
        parsed_pdf_data=parsed_pdf_data,
        normalized=normalized_data,
        pdf_path=pdf_path
    )

    # 10. Run ATC (Additional Terms and Conditions) Compliance Analysis
    atc_result = {}
    if ENABLE_ATC_ANALYSIS and (os.getenv("GEMINI_API_KEY") or os.getenv("ATC_LLM_PROVIDER") == "local_qwen"):
        try:
            atc_result = analyze_bid_atc(
                bid_no=safe_bid_no,
                markdown_text=pdf_text,
                hyperlinks=bid_hyperlinks,
                save_dir=bid_dir
            )
        except Exception as e:
            log.warning(f"ATC analysis encountered an error for {safe_bid_no}: {e}")

    # 11. Assemble Final Unified JSON Schema Artifact inside downloads/<Bid_No>/
    final_bid = {
        "_id": safe_bid_no,
        "bid": card_data.get("bid", {}),
        "card": card_data.get("card", {}),
        "pdf": parsed_pdf_data,
        "hyperlinks": bid_hyperlinks,          # ← all URI links extracted from the PDF
        "normalized": normalized_data,
        "validation": validation_data,
        "atc_analysis": atc_result,
        "telemetry": {
            "ocr": ocr_usage_data,
        },
        "full_pdf_text": pdf_text,
    }
    json_path = os.path.join(bid_dir, f"{safe_bid_no}.json")
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(final_bid, f, indent=4, ensure_ascii=False)
    except Exception as e:
        log.warning(f"Could not save JSON for {safe_bid_no}: {e}")

    # 12. Upsert Record into SQLite & ChromaDB Vector Store
    card_items = card_data.get("card", {}).get("items", [])
    item_names = [it.get("name", "") for it in card_items if it.get("name")]
    item_name = ", ".join(item_names) if item_names else (card_items[0].get("name", "") if card_items else "")

    total_qty_sum = sum(int(it.get("quantity") or 0) for it in card_items if str(it.get("quantity", "")).isdigit())
    if total_qty_sum > 0:
        qty_val = str(total_qty_sum)
    else:
        qty_val = str(card_items[0].get("quantity", "")) if card_items else ""

    card_depts = card_data.get("card", {}).get("departments", [])
    dept_name = ""
    if card_depts:
        dept_name = card_depts[0].get("department_name", "") or card_depts[0].get("name", "")

    bid_packet_type_val = ""
    bt_data = parsed_pdf_data.get("bid_type")
    if isinstance(bt_data, dict):
        bid_packet_type_val = bt_data.get("type_of_bid", "")
    elif isinstance(bt_data, str):
        bid_packet_type_val = bt_data

    # Use normalized estimated value in INR if present, or parsed fallback
    est_val_inr = normalized_data.get("financials", {}).get("estimated_value_inr")
    if est_val_inr:
        est_val_str = str(int(est_val_inr))
    else:
        est_val_str = str(parsed_pdf_data.get("financials", {}).get("estimated_value") or "")

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
        "estimated_value": est_val_str,
        "bid_packet_type": str(bid_packet_type_val or ""),
        "corrigendum_url": str(corr_url or ""),
        "full_pdf_text":   clean_text(pdf_text),
        "atc_analysis":    atc_result.get("raw_markdown", ""),
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
    worker: Optional[AsyncWorker] = None,
    bid_type_name: str = "Product Bid/RAs",
    seen_urls: Optional[set] = None,
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

                    res = None
                    last_err = None
                    for attempt in range(1, MAX_RETRIES_PER_BID + 1):
                        try:
                            res = process_card_item(
                                card=card,
                                browser=browser,
                                db=db,
                                worker=worker,
                                bid_type_name=bid_type_name,
                            )
                            if res.get("status") == "success":
                                break
                            elif res.get("status") == "error_download":
                                log.warning(
                                    f"  Attempt {attempt}/{MAX_RETRIES_PER_BID} download failed for card {i}"
                                )
                                if attempt < MAX_RETRIES_PER_BID:
                                    backoff = RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
                                    log.info(f"  Backing off for {backoff:.1f}s before retry...")
                                    time.sleep(backoff)
                            else:
                                break
                        except Exception as e:
                            last_err = e
                            log.warning(f"  Attempt {attempt}/{MAX_RETRIES_PER_BID} error for card {i}: {e}")
                            if attempt < MAX_RETRIES_PER_BID:
                                backoff = RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
                                log.info(f"  Backing off for {backoff:.1f}s before retry...")
                                time.sleep(backoff)

                    if res and res.get("status") == "success":
                        collected += 1
                        stats["scraped"] += 1
                        if res.get("is_new"):
                            stats["new"] += 1
                        log.info(
                            f"  [{collected}/{TARGET_PER_TYPE}] {res['bid_no']} | "
                            f"Item: {res['item'][:40]} | {'NEW' if res.get('is_new') else 'seen'}"
                        )
                        sleep_between_cards()
                    else:
                        stats["errors"] += 1
                        if last_err:
                            log.error(f"  Card {i} failed after {MAX_RETRIES_PER_BID} attempts: {last_err}")
                except Exception as e:
                    log.error(f"  Card {i} unexpected error: {e}")
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

    is_mineru = (OCR_PROVIDER == "mineru")
    worker = None

    if is_mineru:
        worker = AsyncWorker()
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
            res = None
            last_err = None
            for attempt in range(1, MAX_RETRIES_PER_BID + 1):
                try:
                    res = process_card_item(
                        card=card,
                        browser=browser,
                        db=db,
                        worker=worker,
                        bid_type_name="Product Bid/RAs",
                    )
                    if res.get("status") == "success":
                        break
                    elif res.get("status") == "error_download":
                        log.warning(f"  Attempt {attempt}/{MAX_RETRIES_PER_BID} download failed for {bid_no}")
                        if attempt < MAX_RETRIES_PER_BID:
                            backoff = RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
                            log.info(f"  Backing off for {backoff:.1f}s before retry...")
                            time.sleep(backoff)
                except Exception as e:
                    last_err = e
                    log.warning(f"  Attempt {attempt}/{MAX_RETRIES_PER_BID} failed for {bid_no}: {e}")
                    if attempt < MAX_RETRIES_PER_BID:
                        backoff = RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
                        log.info(f"  Backing off for {backoff:.1f}s before retry...")
                        time.sleep(backoff)
            return res or {"status": "error", "error": str(last_err)}
    finally:
        if is_mineru and worker:
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

    is_mineru = (OCR_PROVIDER == "mineru")
    worker = None

    if is_mineru:
        worker = AsyncWorker()
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
        if is_mineru and worker:
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