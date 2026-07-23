"""
General Standalone GeM Bid Scraper and Benchmark Script.

This script launches a stealth Playwright browser session, retrieves ongoing bids from the GeM portal,
downloads PDF documents, converts them to Markdown using the Mineru VLM engine, parses section fields,
and records granular stage-by-stage timing metrics (HTML save, PDF download, analysis, JSON compilation).
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
        """Stop the background spinner process and print completion status."""
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


def scrape_bids(num_cards=1):
    """
    Scrape specified number of bids from GeM listing page and record timing metrics for each step.
    
    Args:
        num_cards (int): Target number of cards to process (default 1).
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
            print("Opening GeM portal...")
            browser.open_gem()
            
            bid_type_name = "Product Bid/RAs"
            print(f"Selecting bid type: {bid_type_name}...")
            browser.reset_filters()
            browser.select_bid_type(bid_type_name)
            browser.select_ongoing_bids()
            
            print("Waiting for cards to load...")
            browser.wait_for_cards()
            
            cards = browser.get_cards()
            total_cards_available = cards.count()
            
            if total_cards_available == 0:
                print("No cards found.")
                return

            cards_to_pull = min(num_cards, total_cards_available)
            print(f"\nFound {total_cards_available} cards on the page.")
            print(f"Preparing to extract data for {cards_to_pull} card(s)...\n")

            os.makedirs("Scrape_Data", exist_ok=True)

            scraping_times = []

            for i in range(cards_to_pull):
                print(f"--- Processing Card {i + 1} of {cards_to_pull} ---")
                card_start_time = time.time()
                
                card_timings = {
                    "html_save": 0.0,
                    "bid_dl": 0.0,
                    "ra_dl": 0.0,
                    "pdf_save": 0.0,
                    "analyze": 0.0,
                    "md_save": 0.0,
                    "json_save": 0.0,
                    "total": 0.0
                }
                
                card = cards.nth(i)
                card_data = get_card_details(card, bid_type_name)
                doc_url, ra_url, corr_url = browser.extract_card_links(card)
                
                if "card" in card_data:
                    card_data["card"]["bid_pdf_url"] = doc_url
                    card_data["card"]["ra_pdf_url"] = ra_url

                bid_no = card_data.get("bid", {}).get("bid_no", f"unknown_bid_{i}").replace('/', '_')
                print(f"Found Bid: {bid_no}")
                print(f"Document URL: {doc_url}")
                if ra_url:
                    print(f"RA Document URL: {ra_url}")
                
                # Timing: Save HTML Card
                t0 = time.time()
                card_html_path = os.path.join("Scrape_Data", f"{bid_no}.html")
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
                    
                    if ra_url:
                        print("Downloading RA PDF...")
                        t0 = time.time()
                        ra_pdf_path = browser.download_pdf(ra_url)
                        card_timings["ra_dl"] = time.time() - t0
                    
                    t0 = time.time()
                    if pdf_path and os.path.exists(pdf_path):
                        dest_pdf = os.path.join("Scrape_Data", f"{bid_no}.pdf")
                        shutil.copy(pdf_path, dest_pdf)
                        print(f"Copied Bid PDF to {dest_pdf}")
                        
                    if ra_pdf_path and os.path.exists(ra_pdf_path):
                        dest_ra_pdf = os.path.join("Scrape_Data", f"{bid_no}_RA.pdf")
                        shutil.copy(ra_pdf_path, dest_ra_pdf)
                        print(f"Copied RA PDF to {dest_ra_pdf}")
                    card_timings["pdf_save"] = time.time() - t0
                    
                    if pdf_path and os.path.exists(pdf_path):
                        t0 = time.time()
                        conv_timer = ProgressTimer(f"Converting PDF ({bid_no}) to Markdown Via Mineru VLLM Server")
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
                        pdf_md_path = os.path.join("Scrape_Data", f"{bid_no}.md")
                        with open(pdf_md_path, "w", encoding="utf-8-sig") as f:
                            f.write(pdf_text)
                        card_timings["md_save"] = time.time() - t0
                        print(f"Saved PDF Markdown to {pdf_md_path}")
                    else:
                        print("Failed to download PDF.")
                
                final_bid = {
                    "_id": "MongoDB document ID", 
                    "bid": card_data.get("bid", {}),
                    "card": card_data.get("card", {}),
                    "pdf": parsed_pdf_data,
                    "normalized": {}, 
                    "validation": {
                        "issues": []
                    },
                    "full_pdf_text": pdf_text 
                }

                t0 = time.time()
                json_path = os.path.join("Scrape_Data", f"{bid_no}.json")
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(final_bid, f, indent=4, ensure_ascii=False)
                card_timings["json_save"] = time.time() - t0
                print(f"Saved final assembled JSON to {json_path}")
                
                card_timings["total"] = time.time() - card_start_time
                scraping_times.append(card_timings)
                
                print("\n--- Card Timing Breakdown ---")
                print(f"HTML Save:    {card_timings['html_save']:.4f}s")
                print(f"Bid PDF DL:   {card_timings['bid_dl']:.4f}s")
                print(f"RA PDF DL:    {card_timings['ra_dl']:.4f}s")
                print(f"PDF Save:     {card_timings['pdf_save']:.4f}s")
                print(f"Analyze:      {card_timings['analyze']:.4f}s")
                print(f"MD Save:      {card_timings['md_save']:.4f}s")
                print(f"JSON Save:    {card_timings['json_save']:.4f}s")
                print(f"Total Time:   {card_timings['total']:.2f}s\n")

            print("All requested cards have been processed and saved successfully.")
            
            if scraping_times:
                total_times = [t["total"] for t in scraping_times]
                avg_html = sum(t["html_save"] for t in scraping_times) / len(scraping_times)
                avg_bid = sum(t["bid_dl"] for t in scraping_times) / len(scraping_times)
                avg_ra = sum(t["ra_dl"] for t in scraping_times) / len(scraping_times)
                avg_pdf = sum(t["pdf_save"] for t in scraping_times) / len(scraping_times)
                avg_analyze = sum(t["analyze"] for t in scraping_times) / len(scraping_times)
                avg_md = sum(t["md_save"] for t in scraping_times) / len(scraping_times)
                avg_json = sum(t["json_save"] for t in scraping_times) / len(scraping_times)
                
                print("\n" + "="*50)
                print("         SCRAPING TIME METRICS (AVERAGES)")
                print("="*50)
                print(f"Total Cards Processed : {len(scraping_times)}")
                print(f"Avg HTML Save Time    : {avg_html:.4f} seconds")
                print(f"Avg Bid PDF DL Time   : {avg_bid:.4f} seconds")
                print(f"Avg RA PDF DL Time    : {avg_ra:.4f} seconds")
                print(f"Avg PDF Save Time     : {avg_pdf:.4f} seconds")
                print(f"Avg Analyze Time      : {avg_analyze:.4f} seconds")
                print(f"Avg MD Save Time      : {avg_md:.4f} seconds")
                print(f"Avg JSON Save Time    : {avg_json:.4f} seconds")
                print("-" * 50)
                print(f"Minimum Total Time    : {min(total_times):.2f} seconds")
                print(f"Maximum Total Time    : {max(total_times):.2f} seconds")
                print(f"Average Total Time    : {sum(total_times)/len(total_times):.2f} seconds")
                print("="*50 + "\n")

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
    scrape_bids(num_cards=1)