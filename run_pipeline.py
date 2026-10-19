# =========================================================================
# run_pipeline.py
# Unified End-to-End Pipeline Runner (Scraper -> Document -> ATC/RAG -> Search)
# =========================================================================
import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config.settings import DOWNLOAD_DIR
from core.embedder import embed_query, generate_bid_embeddings
from core.normalizer import normalize_bid_data, validate_bid_data
from core.parser import parse_bid_data
from storage.postgres_db import PostgresBidDatabase, get_db_cursor
from utils.logger import get_logger
from utils.pdf_hyperlinks import extract_hyperlinks
from utils.s3_storage import (
    ensure_bucket_exists,
    upload_file,
    upload_bytes,
    download_bytes,
    object_exists,
)

log = get_logger("unified_pipeline")


def print_banner(step: int, title: str):
    print("\n" + "=" * 75)
    print(f" 🚀 [STEP {step}/4] {title}")
    print("=" * 75)


def run_pipeline(live_scrape: bool = False, bid_no: str = None):
    print("\n" + "#" * 75)
    print("  GeMBridge Unified Pipeline: Scraper -> Document -> RAG -> Query")
    print("#" * 75)

    db = PostgresBidDatabase()
    ensure_bucket_exists()

    target_bid_dir = None
    target_safe_bid_no = None
    pdf_bytes = None
    card_data = {}
    raw_doc = None
    pdf_text = ""
    bid_hyperlinks = []

    # =========================================================================
    # STEP 1: SCRAPER (Playwright Web Crawl or Existing Tender Selection)
    # =========================================================================
    print_banner(1, "SCRAPER: Ingest Tender Document & PDFs")

    if live_scrape:
        print("  --> Launching Playwright Chromium in stealth mode...")
        from core.browser import GemBrowser
        from core.parser import get_card_details

        browser = GemBrowser()
        try:
            browser.start()
            browser.goto("https://bidplus.gem.gov.in/all-bids")
            browser.wait_for_cards()
            cards = browser.get_all_cards()
            if not cards:
                print("  ❌ No tender cards found on GeM portal. Falling back to local tender.")
                live_scrape = False
            else:
                card = cards[0]
                card_data = get_card_details(card, "Product Bid/RAs")
                raw_bid_no = card_data.get("bid", {}).get("bid_no", "GEM_LIVE_TEST")
                target_safe_bid_no = raw_bid_no.replace("/", "_")

                doc_url, ra_url, _ = browser.extract_card_links(card)
                if doc_url:
                    print(f"  --> Downloading PDF into memory for tender {raw_bid_no} (Zero-Disk)...")
                    pdf_bytes = browser.download_pdf_to_memory(doc_url)
                    if pdf_bytes:
                        s3_key = f"bids/{target_safe_bid_no}/bid.pdf"
                        upload_bytes(s3_key, pdf_bytes, content_type="application/pdf")
                        print(f"  ✅ Uploaded {len(pdf_bytes):,} bytes to MinIO S3: s3://gem-tenders/{s3_key}")
                    else:
                        print("  ⚠️ In-memory download failed to capture bytes.")

                print(f"  ✅ Scraped live tender: {raw_bid_no} (Zero local files created)")
        finally:
            browser.close()

    if not live_scrape:
        if bid_no:
            target_safe_bid_no = bid_no.replace("/", "_")
            s3_pdf_key = f"bids/{target_safe_bid_no}/bid.pdf"
            if object_exists(s3_pdf_key):
                print(f"  --> Found tender in MinIO S3: s3://gem-tenders/{s3_pdf_key}")
                pdf_bytes = download_bytes(s3_pdf_key)
            else:
                candidate_dir = Path(DOWNLOAD_DIR) / target_safe_bid_no
                if candidate_dir.exists():
                    target_bid_dir = str(candidate_dir)
                else:
                    json_pattern = str(PROJECT_ROOT / "downloads" / "*" / "*.json")
                    all_json_files = glob.glob(json_pattern)
                    matches = [f for f in all_json_files if target_safe_bid_no in f]
                    if matches:
                        target_bid_dir = str(Path(matches[0]).parent)
                    else:
                        print(f"  ❌ Specified tender '{bid_no}' not found in MinIO or downloads/!")
                        return
        else:
            json_pattern = str(PROJECT_ROOT / "downloads" / "*" / "*.json")
            all_json_files = glob.glob(json_pattern)
            primary_files = [f for f in all_json_files if Path(f).stem == Path(f).parent.name]
            if not primary_files:
                print("  ❌ No existing tender packages found in downloads/!")
                return
            target_bid_dir = str(Path(primary_files[0]).parent)
            target_safe_bid_no = Path(primary_files[0]).stem

        if target_bid_dir:
            print(f"  --> Using local tender package: {target_safe_bid_no}")
            print(f"  --> Directory: {target_bid_dir}")
            pdf_file = Path(target_bid_dir) / "bid.pdf"
            if pdf_file.exists():
                s3_key = f"bids/{target_safe_bid_no}/bid.pdf"
                try:
                    upload_file(s3_key, str(pdf_file), content_type="application/pdf")
                    print(f"  ✅ Uploaded PDF to MinIO S3: s3://gem-tenders/{s3_key}")
                except Exception as e:
                    print(f"  ⚠️ MinIO upload note: {e}")

    # =========================================================================
    # STEP 2: DOCUMENT PROCESSING & RELATIONAL INGESTION (PostgreSQL)
    # =========================================================================
    print_banner(2, "DOCUMENT PROCESSOR: Parse, Normalize & Ingest into PostgreSQL")

    if pdf_bytes:
        print(f"  --> Parsing in-memory PDF ({len(pdf_bytes):,} bytes) with PyMuPDF & Core Parser...")
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pdf_text = "\n".join([page.get_text() for page in doc])
        doc.close()

        try:
            bid_hyperlinks = extract_hyperlinks(pdf_bytes, source="bid")
        except Exception:
            bid_hyperlinks = []

        if not card_data:
            card_data = {
                "bid": {"bid_no": target_safe_bid_no.replace("_", "/"), "product_type": "PRODUCT"},
                "card": {"bid_no": target_safe_bid_no.replace("_", "/")},
            }

        product_type = card_data.get("bid", {}).get("product_type", "PRODUCT")
        parsed_pdf_data = parse_bid_data(pdf_text, product_type)

        import re
        if not parsed_pdf_data.get("timing", {}).get("bid_end_datetime"):
            m_end = re.search(r'Bid End Date/Time\s*\n\s*(\d{2}-\d{2}-\d{4}\s+\d{1,2}:\d{2}:\d{2})', pdf_text, re.IGNORECASE)
            if m_end:
                parsed_pdf_data.setdefault("timing", {})["bid_end_datetime"] = m_end.group(1).strip()

        if not parsed_pdf_data.get("timing", {}).get("bid_opening_datetime"):
            m_open = re.search(r'Bid Opening[\s\S]{0,30}?Date/Time\s*\n\s*(\d{2}-\d{2}-\d{4}\s+\d{1,2}:\d{2}:\d{2})', pdf_text, re.IGNORECASE)
            if m_open:
                parsed_pdf_data.setdefault("timing", {})["bid_opening_datetime"] = m_open.group(1).strip()

        if not parsed_pdf_data.get("departments", {}).get("organisation_name"):
            m_org = re.search(r'Organisation Name\s*\n\s*([^\n]+)', pdf_text, re.IGNORECASE)
            if m_org:
                parsed_pdf_data.setdefault("departments", {})["organisation_name"] = m_org.group(1).strip()

        if not parsed_pdf_data.get("departments", {}).get("department_name"):
            m_dept = re.search(r'Department Name\s*\n\s*([^\n]+)', pdf_text, re.IGNORECASE)
            if m_dept:
                parsed_pdf_data.setdefault("departments", {})["department_name"] = m_dept.group(1).strip()

        if not parsed_pdf_data.get("departments", {}).get("ministry_state_name"):
            m_min = re.search(r'Ministry/State Name\s*\n\s*([^\n]+)', pdf_text, re.IGNORECASE)
            if m_min:
                parsed_pdf_data.setdefault("departments", {})["ministry_state_name"] = m_min.group(1).strip()

        normalized_data = normalize_bid_data(card_data, parsed_pdf_data, pdf_text)
        validation_data = validate_bid_data(
            bid_no=target_safe_bid_no,
            card_data=card_data,
            parsed_pdf_data=parsed_pdf_data,
            normalized=normalized_data,
            pdf_path=f"s3://gem-tenders/bids/{target_safe_bid_no}/bid.pdf",
        )

        raw_doc = {
            "_id": target_safe_bid_no,
            "bid": card_data.get("bid", {}),
            "card": card_data.get("card", {}),
            "pdf": parsed_pdf_data,
            "hyperlinks": bid_hyperlinks,
            "normalized": normalized_data,
            "validation": validation_data,
            "atc_analysis": {},
            "full_pdf_text": pdf_text,
        }

        # Stream directly to MinIO without local disk write
        meta_bytes = json.dumps(raw_doc, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        upload_bytes(f"bids/{target_safe_bid_no}/metadata.json", meta_bytes, content_type="application/json")
        print(f"  ✅ Uploaded metadata.json directly to MinIO (Zero-Disk) ({len(pdf_text):,} characters extracted)")

    else:
        final_json = Path(target_bid_dir) / f"{target_safe_bid_no}.json"
        card_json = Path(target_bid_dir) / "card_data.json"
        pdf_file = Path(target_bid_dir) / "bid.pdf"

        if not final_json.exists():
            if not pdf_file.exists():
                print(f"  ❌ Neither JSON nor PDF found in: {target_bid_dir}")
                return

            print(f"  --> Parsing downloaded PDF with PyMuPDF & Core Parser...")
            import fitz
            doc = fitz.open(str(pdf_file))
            pdf_text = "\n".join([page.get_text() for page in doc])
            doc.close()

            # Extract hyperlinks
            bid_hyperlinks = []
            try:
                bid_hyperlinks = extract_hyperlinks(str(pdf_file))
            except Exception:
                pass

            # Load card data if present
            card_data = {}
            if card_json.exists():
                with open(card_json, "r", encoding="utf-8") as fp:
                    card_data = json.load(fp)
            else:
                card_data = {
                    "bid": {"bid_no": target_safe_bid_no.replace("_", "/"), "product_type": "PRODUCT"},
                    "card": {"bid_no": target_safe_bid_no.replace("_", "/")},
                }

            product_type = card_data.get("bid", {}).get("product_type", "PRODUCT")
            parsed_pdf_data = parse_bid_data(pdf_text, product_type)

            import re
            # Text fallbacks for timing if table parsing did not capture them
            if not parsed_pdf_data.get("timing", {}).get("bid_end_datetime"):
                m_end = re.search(r'Bid End Date/Time\s*\n\s*(\d{2}-\d{2}-\d{4}\s+\d{1,2}:\d{2}:\d{2})', pdf_text, re.IGNORECASE)
                if m_end:
                    parsed_pdf_data.setdefault("timing", {})["bid_end_datetime"] = m_end.group(1).strip()

            if not parsed_pdf_data.get("timing", {}).get("bid_opening_datetime"):
                m_open = re.search(r'Bid Opening[\s\S]{0,30}?Date/Time\s*\n\s*(\d{2}-\d{2}-\d{4}\s+\d{1,2}:\d{2}:\d{2})', pdf_text, re.IGNORECASE)
                if m_open:
                    parsed_pdf_data.setdefault("timing", {})["bid_opening_datetime"] = m_open.group(1).strip()

            if not parsed_pdf_data.get("departments", {}).get("organisation_name"):
                m_org = re.search(r'Organisation Name\s*\n\s*([^\n]+)', pdf_text, re.IGNORECASE)
                if m_org:
                    parsed_pdf_data.setdefault("departments", {})["organisation_name"] = m_org.group(1).strip()

            if not parsed_pdf_data.get("departments", {}).get("department_name"):
                m_dept = re.search(r'Department Name\s*\n\s*([^\n]+)', pdf_text, re.IGNORECASE)
                if m_dept:
                    parsed_pdf_data.setdefault("departments", {})["department_name"] = m_dept.group(1).strip()

            if not parsed_pdf_data.get("departments", {}).get("ministry_state_name"):
                m_min = re.search(r'Ministry/State Name\s*\n\s*([^\n]+)', pdf_text, re.IGNORECASE)
                if m_min:
                    parsed_pdf_data.setdefault("departments", {})["ministry_state_name"] = m_min.group(1).strip()

            normalized_data = normalize_bid_data(card_data, parsed_pdf_data, pdf_text)
            validation_data = validate_bid_data(
                bid_no=target_safe_bid_no,
                card_data=card_data,
                parsed_pdf_data=parsed_pdf_data,
                normalized=normalized_data,
                pdf_path=str(pdf_file),
            )

            raw_doc = {
                "_id": target_safe_bid_no,
                "bid": card_data.get("bid", {}),
                "card": card_data.get("card", {}),
                "pdf": parsed_pdf_data,
                "hyperlinks": bid_hyperlinks,
                "normalized": normalized_data,
                "validation": validation_data,
                "atc_analysis": {},
                "full_pdf_text": pdf_text,
            }

            with open(final_json, "w", encoding="utf-8") as fp:
                json.dump(raw_doc, fp, ensure_ascii=False, indent=4, default=str)
            print(f"  ✅ Assembled & Saved {final_json.name} ({len(pdf_text)} characters extracted)")

        else:
            with open(final_json, "r", encoding="utf-8") as fp:
                raw_doc = json.load(fp)
            pdf_text = raw_doc.get("full_pdf_text", "")

    t0 = time.time()
    db.upsert_bid(raw_doc)
    ingest_time_ms = (time.time() - t0) * 1000

    print(f"  ✅ Master Tender & Child Records Upserted in {ingest_time_ms:.2f}ms")
    with get_db_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) FROM bid_items WHERE bid_id = %s;", (target_safe_bid_no,))
        items_cnt = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM bid_consignees WHERE bid_id = %s;", (target_safe_bid_no,))
        cons_cnt = cur.fetchone()[0]
        print(f"  --> Database Record: {items_cnt} line items, {cons_cnt} consignee delivery locations")

    # =========================================================================
    # STEP 3: ATC COMPLIANCE & VECTOR EMBEDDINGS (RAG)
    # =========================================================================
    print_banner(3, "RAG VECTOR ENGINE: Generate 768-dim BGE Embeddings & Store in pgvector")

    atc_data = raw_doc.get("atc_analysis")
    pdf_text = raw_doc.get("full_pdf_text", "")

    print(f"  --> Chunking tender text into Item, Compliance & PDF passages...")
    t0 = time.time()
    chunks = generate_bid_embeddings(raw_doc, atc_result=atc_data, pdf_text=pdf_text)
    embed_time = time.time() - t0

    if chunks:
        indexed_count = db.insert_chunks(target_safe_bid_no, chunks)
        print(f"  ✅ Generated & Indexed {indexed_count} Vector Chunks in {embed_time:.2f}s")
        print(f"  --> Vector Dimension: 768 (BAAI/bge-base-en-v1.5)")
        print(f"  --> Index Type: PostgreSQL 16 HNSW Cosine Index")
    else:
        print("  ⚠️ No chunks generated.")

    # =========================================================================
    # STEP 4: RAG SEMANTIC RETRIEVAL QUERY (Instant AI Search)
    # =========================================================================
    print_banner(4, "RAG QUERY TEST: Execute Real-Time Semantic Search")

    sample_query = "specifications, warranty, and mandatory document requirements"
    print(f"  --> Asking Question: \"{sample_query}\"")

    t0 = time.time()
    query_vec = embed_query(sample_query)
    results = db.search_chunks(query_vec, top_k=2, bid_id=target_safe_bid_no)
    search_latency_ms = (time.time() - t0) * 1000

    print(f"  ✅ Search Finished in {search_latency_ms:.2f}ms (Target: < 50ms)")
    print(f"  --> Top Retrieved Matches ({len(results)} chunks):")
    for idx, r in enumerate(results, 1):
        dist = float(r.get("distance", 1.0))
        sim = max(0.0, 1.0 - dist)
        print(f"\n      [{idx}] Type: {r.get('chunk_type')} | Similarity: {sim:.1%} (Distance: {dist:.4f})")
        snippet = (r.get("chunk_text") or "").strip().replace("\n", " ")[:140]
        print(f"          Snippet: \"{snippet}...\"")

    print("\n" + "=" * 75)
    print(f" 🎉 SUCCESS! Entire Pipeline Ran Smoothly for: {target_safe_bid_no}")
    print("=" * 75)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run GeMBridge End-to-End Pipeline")
    parser.add_argument("--live", action="store_true", help="Scrape live tender from GeM portal via Playwright")
    parser.add_argument("--bid", type=str, default=None, help="Target specific Bid No / ID")
    args = parser.parse_args()

    run_pipeline(live_scrape=args.live, bid_no=args.bid)
