"""
main.py
GeMBridge Enterprise Pipeline CLI Entrypoint (v3.0.0)

Single-command execution for development, testing, and resource profiling.
Compatible with: .\benchmark.ps1 -Command "python main.py --once"

Usage:
  python main.py --once                          # Scrape 1 live tender of default type and run full pipeline
  python main.py --once --all-types              # Scrape 1 live tender per GeM category across all 9 types
  python main.py --once --bid-type "BOQ Bids"    # Scrape 1 live tender of a specific category
  python main.py --once --target 2               # Scrape 2 tenders
  python main.py --once --offline                # Profile full pipeline on cached data without browser
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output on Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config.settings import BID_TYPES, GEM_ALL_BIDS, DOWNLOAD_DIR
from core.browser import GemBrowser
from core.embedder import embed_query, generate_bid_embeddings
from core.normalizer import normalize_bid_data, validate_bid_data
from core.parser import get_card_details, parse_bid_data
from storage.postgres_db import PostgresBidDatabase, get_db_cursor
from utils.logger import get_logger
from utils.pdf_hyperlinks import extract_hyperlinks
from utils.s3_storage import (
    ensure_bucket_exists,
    upload_bytes,
    upload_file,
    object_exists,
    download_bytes,
)

log = get_logger("gem_main")


def process_single_tender_pipeline(card_data: dict, pdf_bytes: bytes, safe_bid_no: str, db: PostgresBidDatabase):
    """
    Executes the entire Zero-Disk In-Memory Pipeline for one tender:
    1. MinIO S3 Stream Upload
    2. PyMuPDF In-Memory Text Extraction & Table Parsing
    3. Normalization & Validation
    4. ACID PostgreSQL Ingestion (10 relational tables)
    5. 768-dim BGE Vector Embeddings Generation
    6. pgvector HNSW Cosine Indexing
    """
    print(f"\n[{safe_bid_no}] Step 1/4: Streaming PDF to MinIO S3...")
    s3_key = f"bids/{safe_bid_no}/bid.pdf"
    upload_bytes(s3_key, pdf_bytes, content_type="application/pdf")
    print(f"[{safe_bid_no}]  -> Uploaded {len(pdf_bytes):,} bytes to MinIO (s3://gem-tenders/{s3_key})")

    print(f"[{safe_bid_no}] Step 2/4: Parsing In-Memory PDF with PyMuPDF...")
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pdf_text = "\n".join([page.get_text() for page in doc])
    doc.close()

    try:
        bid_hyperlinks = extract_hyperlinks(pdf_bytes, source="bid")
    except Exception:
        bid_hyperlinks = []

    product_type = card_data.get("bid", {}).get("product_type", "PRODUCT")
    parsed_pdf_data = parse_bid_data(pdf_text, product_type)

    normalized_data = normalize_bid_data(card_data, parsed_pdf_data, pdf_text)
    validation_data = validate_bid_data(
        bid_no=safe_bid_no,
        card_data=card_data,
        parsed_pdf_data=parsed_pdf_data,
        normalized=normalized_data,
        pdf_path=f"s3://gem-tenders/{s3_key}",
    )

    raw_doc = {
        "_id": safe_bid_no,
        "bid": card_data.get("bid", {}),
        "card": card_data.get("card", {}),
        "pdf": parsed_pdf_data,
        "hyperlinks": bid_hyperlinks,
        "normalized": normalized_data,
        "validation": validation_data,
        "atc_analysis": {},
        "full_pdf_text": pdf_text,
    }

    # Stream metadata.json directly to MinIO
    meta_bytes = json.dumps(raw_doc, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    upload_bytes(f"bids/{safe_bid_no}/metadata.json", meta_bytes, content_type="application/json")

    print(f"[{safe_bid_no}] Step 3/4: Upserting ACID record into PostgreSQL 18...")
    t0 = time.time()
    db.upsert_bid(raw_doc)
    upsert_ms = (time.time() - t0) * 1000
    print(f"[{safe_bid_no}]  -> Master & child records upserted in {upsert_ms:.2f}ms")

    print(f"[{safe_bid_no}] Step 4/4: Generating 768-dim BGE Embeddings & pgvector Indexing...")
    t0 = time.time()
    chunks = generate_bid_embeddings(raw_doc, atc_result={}, pdf_text=pdf_text)
    if chunks:
        indexed_count = db.insert_chunks(safe_bid_no, chunks)
        embed_s = time.time() - t0
        print(f"[{safe_bid_no}]  -> Indexed {indexed_count} vector chunks in {embed_s:.2f}s via HNSW cosine index")
    else:
        print(f"[{safe_bid_no}]  -> Warning: No vector chunks generated")

    print(f"[{safe_bid_no}] [OK] Pipeline successfully completed for {safe_bid_no}!\n")


def run_live_scrape(bid_types_to_scrape: list, target_per_type: int = 1):
    """
    Launches Playwright in stealth mode, iterates through specified bid types,
    extracts target_per_type bids per type, and streams them through the pipeline.
    """
    db = PostgresBidDatabase()
    ensure_bucket_exists()

    browser = GemBrowser()
    processed_count = 0

    try:
        print("[*] Launching Chromium Playwright browser context...")
        browser.start()
        browser.goto(GEM_ALL_BIDS)
        browser.wait_for_cards()

        for b_type in bid_types_to_scrape:
            print(f"\n=======================================================")
            print(f" Category: '{b_type}' (Target: {target_per_type})")
            print(f"=======================================================")

            if not browser.select_filter(b_type):
                print(f"[-] Could not click filter for '{b_type}', continuing...")
                continue

            browser.wait_for_cards()
            cards = browser.get_all_cards()
            if not cards:
                print(f"[-] No cards found for category '{b_type}'")
                continue

            type_dispatched = 0
            for card in cards:
                if type_dispatched >= target_per_type:
                    break

                try:
                    card_data = get_card_details(card, b_type)
                    doc_url, ra_url, _ = browser.extract_card_links(card)
                    if not doc_url:
                        continue

                    raw_bid_no = card_data.get("bid", {}).get("bid_no", f"GEM_TEST_{int(time.time())}")
                    safe_bid_no = raw_bid_no.replace("/", "_")

                    print(f"\n[*] Found Tender Card: {raw_bid_no}")
                    print(f"    Item: {card_data.get('card', {}).get('title_item', 'N/A')}")
                    print(f"    Downloading PDF in-memory (Zero-Disk)...")

                    pdf_bytes = browser.download_pdf_to_memory(doc_url)
                    if not pdf_bytes:
                        print(f"    [!] Failed to download PDF bytes for {raw_bid_no}")
                        continue

                    process_single_tender_pipeline(card_data, pdf_bytes, safe_bid_no, db)
                    type_dispatched += 1
                    processed_count += 1

                except Exception as card_err:
                    print(f"[!] Error processing card: {card_err}")

    finally:
        browser.close()
        print("[*] Browser context closed.")

    return processed_count


def run_offline_benchmark():
    """
    Executes the pipeline on an existing cached tender without launching Playwright.
    Provides instant CPU and RAM profiling for data processing and vector embedding.
    """
    db = PostgresBidDatabase()
    ensure_bucket_exists()

    print("[*] Running Offline In-Memory Pipeline Benchmark (Zero-Browser)...")
    # Look for cached PDF in downloads or MinIO
    cached_bids = [d for d in os.listdir(DOWNLOAD_DIR) if os.path.isdir(os.path.join(DOWNLOAD_DIR, d))] if os.path.exists(DOWNLOAD_DIR) else []
    
    if cached_bids:
        safe_bid_no = cached_bids[0]
        pdf_path = os.path.join(DOWNLOAD_DIR, safe_bid_no, f"{safe_bid_no}.pdf")
        if not os.path.exists(pdf_path):
            pdf_path = os.path.join(DOWNLOAD_DIR, safe_bid_no, "bid.pdf")

        if os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

            card_data = {
                "bid": {"bid_no": safe_bid_no.replace("_", "/"), "product_type": "PRODUCT"},
                "card": {"bid_no": safe_bid_no.replace("_", "/"), "title_item": "Benchmark Test Item"},
            }
            process_single_tender_pipeline(card_data, pdf_bytes, safe_bid_no, db)
            return 1

    # Fallback to run_pipeline.py runner
    from run_pipeline import run_pipeline as run_pipe
    run_pipe(live_scrape=False)
    return 1


def run_workers_job(categories: list, target_per_type: int = 1):
    """
    Dispatches crawling tasks to Celery worker queues and tracks their completion.
    """
    from tasks.tier1_scraper import scrape_category
    from tasks.celery_app import app as celery_app

    print(f"[*] Enqueuing {len(categories)} category tasks to Celery scraping_queue...")
    task_handles = []
    for cat in categories:
        res = scrape_category.delay(bid_type=cat, target_count=target_per_type)
        print(f"  -> Dispatched [{cat}] (Target: {target_per_type}) | Task ID: {res.id}")
        task_handles.append((cat, res))

    print(f"\n[*] Waiting for Celery workers to finish processing...")
    completed = 0
    poll_start = time.time()
    while completed < len(task_handles):
        time.sleep(2)
        done_now = sum(1 for cat, t in task_handles if t.ready())
        if done_now != completed:
            completed = done_now
            print(f"  --> Progress: {completed}/{len(task_handles)} categories completed...")
        if time.time() - poll_start > 300:  # 5 mins timeout
            print("  [!] Timeout waiting for worker completion.")
            break
    print("[*] All dispatched worker tasks have finished.")
    return completed


def main():
    parser = argparse.ArgumentParser(description="GeMBridge Unified Pipeline Runner & Benchmarking CLI")
    parser.add_argument("--once", action="store_true", help="Run once and exit cleanly (required for benchmark.ps1)")
    parser.add_argument("--workers", action="store_true", help="Execute via distributed Celery workers instead of in-process")
    parser.add_argument("--all-types", action="store_true", help="Scrape 1 tender for each of the 9 GeM categories")
    parser.add_argument("--bid-type", type=str, default="Product Bid/RAs", help="Specific GeM category to scrape (default: 'Product Bid/RAs')")
    parser.add_argument("--target", type=int, default=1, help="Number of bids to extract per type (default: 1)")
    parser.add_argument("--offline", action="store_true", help="Run offline benchmark on existing tender without Playwright")
    parser.add_argument("--query-test", action="store_true", help="Run verification RAG vector query after completion")

    args = parser.parse_args()

    t_start = time.time()
    mode_str = "Workers Distributed" if args.workers else ("Offline Benchmark" if args.offline else "Live In-Process")
    print("=" * 70)
    print(" GeMBridge Pipeline Execution: Zero-Disk In-Memory Architecture")
    print(f" Mode: {mode_str} | Once: {args.once} | Target Per Type: {args.target}")
    print("=" * 70)

    total_processed = 0
    if args.offline:
        total_processed = run_offline_benchmark()
    else:
        if args.all_types:
            categories = BID_TYPES
            print(f"[*] Multi-Type Mode: Processing {args.target} bid(s) for ALL {len(categories)} categories")
        else:
            categories = [args.bid_type]
            print(f"[*] Single-Type Mode: Processing {args.target} bid(s) for category '{args.bid_type}'")

        if args.workers:
            total_processed = run_workers_job(categories, target_per_type=args.target)
        else:
            total_processed = run_live_scrape(categories, target_per_type=args.target)

    # Verification RAG query
    if args.query_test or total_processed > 0:
        print("\n" + "-" * 70)
        print(" Verifying pgvector Semantic Retrieval...")
        db = PostgresBidDatabase()
        test_q = "equipment specifications delivery and warranty terms"
        t0 = time.time()
        q_vec = embed_query(test_q)
        results = db.search_chunks(q_vec, top_k=2)
        search_ms = (time.time() - t0) * 1000
        print(f" [OK] pgvector Cosine Search executed in {search_ms:.2f}ms (Returned {len(results)} chunks)")
        print("-" * 70)

    elapsed = time.time() - t_start
    print(f"\n[DONE] Execution finished successfully in {elapsed:.2f}s! Total tenders processed: {total_processed}")
    sys.exit(0)


if __name__ == "__main__":
    main()

