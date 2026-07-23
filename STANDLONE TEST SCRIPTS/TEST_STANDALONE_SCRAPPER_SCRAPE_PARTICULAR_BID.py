"""
Standalone Single Specific Bid GeM Scraper Script.

This script uses GeM Advanced Search to query and extract data for a single target Bid Number (e.g. GEM/2026/B/7768206).
It downloads the corresponding bid PDF, converts it to Markdown using the Mineru VLM engine, parses all fields,
and saves the output to HTML, PDF, Markdown, and assembled JSON artifacts.
"""

import os
import sys
import json
import time
import shutil
import asyncio
import threading
import multiprocessing
from pathlib import Path
from contextlib import contextmanager

# Suppress noisy library logs
os.environ["MINERU_LOG_LEVEL"] = "WARNING"
os.environ["VLLM_LOGGING_LEVEL"] = "WARNING"

# Ensure the script can find local modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Mineru_Document_To_Markdown import (
    async_convert_document,
    set_vlm_config,
    async_start_vllm_server,
    close_vllm_server
)
from core.browser import GemBrowser
from core.parser import get_card_details, parse_bid_data


def _run_spinner(description, stop_event):
    """
    Run an animated CLI spinner in a separate multiprocessing process 
    to prevent process locking during long operations.
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
    """A multiprocessing background timer displaying CLI spinner animation and timing."""
    def __init__(self, description):
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
        """Stop the background spinner process and print completion timing."""
        self._stop_event.set()
        if self._process:
            self._process.join()
        elapsed = time.time() - self.start_time
        sys.stdout.write(f"\r✅ {self.description} | Completed in {elapsed:.1f}s" + " " * 15 + "\n")
        sys.stdout.flush()


@contextmanager
def suppress_stdout_stderr():
    """Suppress stdout and stderr at file descriptor level for quiet background execution."""
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
    """Helper class to run async Mineru VLM conversion routines on a background thread/loop."""
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coro):
        """Run coroutine in worker thread loop and return result synchronously."""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()

    def run_sync(self, func, *args, **kwargs):
        """Run synchronous function in worker loop safely."""
        async def _wrapper():
            return func(*args, **kwargs)
        return self.run(_wrapper())

    def stop(self):
        """Cancel pending tasks and terminate the event loop thread."""
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


def scrape_specific_bid(bid_no: str):
    """
    Search and scrape a single specific Bid / RA number via GeM portal advanced search.
    
    Args:
        bid_no (str): Target bid number string (e.g. 'GEM/2026/B/7768206').
    """
    worker = AsyncWorker()

    # 1. Configure VLM batch size & GPU memory utilization
    set_vlm_config(batch_size=16, max_gpu_util=0.8, model_len=4096)

    # 2. Pre-warm and start vLLM server engine quietly with timer
    server_timer = ProgressTimer("Starting Mineru vLLM server")
    server_timer.start()
    try:
        with suppress_stdout_stderr():
            worker.run(async_start_vllm_server())
    finally:
        server_timer.stop()

    try:
        print("Starting browser...")
        with GemBrowser() as browser:
            print(f"Opening GeM Advanced Search for Bid: {bid_no}...")
            browser.advanced_search_bid(bid_no)
            
            print("Waiting for cards to load...")
            browser.wait_for_cards()
            
            cards = browser.get_cards()
            total_cards_available = cards.count()
            
            if total_cards_available == 0:
                print(f"No cards found for Bid: {bid_no}.")
                return

            print(f"\nFound {total_cards_available} card(s) matching the search.")
            bid_type_name = "Product Bid/RAs" 

            os.makedirs("Scrape_Data", exist_ok=True)

            card_start_time = time.time()
            card_timings = {
                "html_save": 0.0, "bid_dl": 0.0, "ra_dl": 0.0,
                "pdf_save": 0.0, "analyze": 0.0, "md_save": 0.0,
                "json_save": 0.0, "total": 0.0
            }
            
            card = cards.nth(0)
            card_data = get_card_details(card, bid_type_name)
            doc_url, ra_url, corr_url = browser.extract_card_links(card)
            
            if "card" in card_data:
                card_data["card"]["bid_pdf_url"] = doc_url
                card_data["card"]["ra_pdf_url"] = ra_url

            safe_bid_no = card_data.get("bid", {}).get("bid_no", bid_no).replace('/', '_')
            print(f"Processing Bid: {safe_bid_no}")
            print(f"Document URL: {doc_url}")
            
            t0 = time.time()
            card_html_path = os.path.join("Scrape_Data", f"{safe_bid_no}.html")
            with open(card_html_path, "w", encoding="utf-8") as f:
                f.write(card.inner_html())
            card_timings["html_save"] = time.time() - t0
            print(f"Saved card HTML to {card_html_path}")
            
            parsed_pdf_data = {}
            pdf_text = ""
            pdf_path = None
            ra_pdf_path = None
            
            if doc_url:
                print("Downloading Bid PDF...")
                t0 = time.time()
                pdf_path = browser.download_pdf(doc_url)
                card_timings["bid_dl"] = time.time() - t0
                
                t0 = time.time()
                if pdf_path and os.path.exists(pdf_path):
                    dest_pdf = os.path.join("Scrape_Data", f"{safe_bid_no}.pdf")
                    shutil.copy(pdf_path, dest_pdf)
                    print(f"Copied Bid PDF to {dest_pdf}")
                card_timings["pdf_save"] = time.time() - t0
                
                if pdf_path and os.path.exists(pdf_path):
                    t0 = time.time()
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
                    finally:
                        conv_timer.stop()
                    
                    product_type = card_data.get("bid", {}).get("product_type", "PRODUCT")
                    parsed_pdf_data = parse_bid_data(pdf_text, product_type)
                    card_timings["analyze"] = time.time() - t0
                    
                    card_data["bid"]["process_kind"] = parsed_pdf_data.pop("process_kind", "")
                    card_data["bid"]["base_type"] = parsed_pdf_data.pop("base_type", "")
                    
                    t0 = time.time()
                    pdf_md_path = os.path.join("Scrape_Data", f"{safe_bid_no}.md")
                    with open(pdf_md_path, "w", encoding="utf-8-sig") as f:
                        f.write(pdf_text)
                    card_timings["md_save"] = time.time() - t0
                    print(f"Saved PDF Markdown to {pdf_md_path}")
                else:
                    print("Failed to download PDF.")
            
            final_bid = {
                "_id": f"{safe_bid_no}", 
                "bid": card_data.get("bid", {}),
                "card": card_data.get("card", {}),
                "pdf": parsed_pdf_data,
                "normalized": {}, 
                "validation": {"issues": []},
                "full_pdf_text": pdf_text 
            }

            t0 = time.time()
            json_path = os.path.join("Scrape_Data", f"{safe_bid_no}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(final_bid, f, indent=4, ensure_ascii=False)
            card_timings["json_save"] = time.time() - t0
            print(f"Saved final assembled JSON to {json_path}")
            
            card_timings["total"] = time.time() - card_start_time
            print(f"\nCompleted processing for {bid_no} in {card_timings['total']:.2f}s.")

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


if __name__ == "__main__":
    target_bid = "GEM/2026/B/7732834"
    scrape_specific_bid(bid_no=target_bid)