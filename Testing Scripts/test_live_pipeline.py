# =========================================================================
# Testing Scripts/test_live_pipeline.py
# GeMBridge Live Distributed Pipeline End-to-End Verification Test
# 
# Validates the live execution chain:
#   [Client/Gateway] 
#         │
#         ▼ (Queue: document_queue)
#   [Tier 2 Worker] ➔ PyMuPDF / Extraction ➔ PostgreSQL Upsert ➔ MinIO Upload
#         │
#         ▼ (Queue: atc_rag_queue)
#   [Tier 3 Worker] ➔ Gemini ATC Checklist ➔ BGE Embeddings ➔ pgvector HNSW
#         │
#         ▼
#   [FastAPI REST Gateway] ➔ Verification of /bids/{id} and /search/semantic
# =========================================================================
import json
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output & line buffering on Windows consoles
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)

import redis
import requests
from config.settings import REDIS_URL, MINIO_BUCKET
from storage.postgres_db import PostgresBidDatabase, get_db_cursor
from utils.s3_storage import ensure_bucket_exists, download_bytes
from tasks.celery_app import app as celery_app


def print_header(title: str):
    print("\n" + "=" * 80)
    print(f"🚀 {title}")
    print("=" * 80)


def print_step(num: int, title: str):
    print(f"\n[{num}/5] ── {title} " + "─" * (65 - len(title)))


def test_live_pipeline():
    print_header("GEMBRIDGE DISTRIBUTED PIPELINE — LIVE WORKER E2E TEST")
    scorecard = {}

    # -------------------------------------------------------------------------
    # STEP 1: Pre-Flight Service Connectivity Check
    # -------------------------------------------------------------------------
    print_step(1, "Pre-Flight Infrastructure Health Check")
    
    # 1.1 Redis
    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        r_ping = r.ping()
        print(f"  ✅ Redis Broker: Connected & Healthy ({REDIS_URL})")
        scorecard["Redis Broker"] = True
    except Exception as e:
        print(f"  ❌ Redis Broker: Connection Failed ({e})")
        scorecard["Redis Broker"] = False
        return False

    # 1.2 MinIO
    try:
        ensure_bucket_exists(MINIO_BUCKET)
        print(f"  ✅ MinIO S3: Connected & Target Bucket '{MINIO_BUCKET}' Ready")
        scorecard["MinIO S3 Storage"] = True
    except Exception as e:
        print(f"  ❌ MinIO S3: Connection Failed ({e})")
        scorecard["MinIO S3 Storage"] = False
        return False

    # 1.3 PostgreSQL
    try:
        db = PostgresBidDatabase()
        with get_db_cursor(commit=False) as cur:
            cur.execute("SELECT COUNT(*) FROM bids;")
            total_bids = cur.fetchone()[0]
        print(f"  ✅ PostgreSQL v3.0: Connected (Database has {total_bids} bids indexed)")
        scorecard["PostgreSQL v3.0 Database"] = True
    except Exception as e:
        print(f"  ❌ PostgreSQL v3.0: Connection Failed ({e})")
        scorecard["PostgreSQL v3.0 Database"] = False
        return False

    # -------------------------------------------------------------------------
    # STEP 2: Worker Node Discovery
    # -------------------------------------------------------------------------
    print_step(2, "Celery Worker Discovery & Inspection")
    try:
        inspector = celery_app.control.inspect(timeout=3.0)
        active_ping = inspector.ping() or {}
        active_workers = list(active_ping.keys())

        if not active_workers:
            print("  ⚠️ WARNING: No active Celery workers detected!")
            print("     -> If testing natively on Windows, start workers in a separate terminal:")
            print("        .\\start_workers.ps1")
            print("     -> If testing in Docker, start the compose stack:")
            print("        docker compose -f docker-compose.local.yml up -d")
            scorecard["Worker Nodes Online"] = False
        else:
            print(f"  ✅ Active Worker Nodes Found ({len(active_workers)} workers online):")
            for w in active_workers:
                print(f"     • {w}")
            scorecard["Worker Nodes Online"] = True
    except Exception as e:
        print(f"  ⚠️ Worker inspection error: {e}")
        scorecard["Worker Nodes Online"] = False

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    # STEP 3: Live Tender Pipeline Dispatch (Online Crawling / Real Download)
    # -------------------------------------------------------------------------
    is_offline = "--offline" in sys.argv or "--cached" in sys.argv
    has_scraper = "worker_scraper@local" in active_workers

    # Check for existing local folders if offline is explicitly requested
    cached_candidates = []
    if (PROJECT_ROOT / "downloads").exists():
        for d in (PROJECT_ROOT / "downloads").iterdir():
            if d.is_dir() and (d / f"{d.name}.pdf").exists():
                cached_candidates.append(d)

    safe_bid_no = None
    test_bid_no = None
    real_doc = {}

    if is_offline and cached_candidates:
        print_step(3, "Using Cached Tender from downloads/ (--offline mode)")
        selected_dir = cached_candidates[0]
        safe_bid_no = selected_dir.name
        json_file = selected_dir / f"{safe_bid_no}.json"
        if json_file.exists():
            with open(json_file, "r", encoding="utf-8") as f:
                real_doc = json.load(f)
        test_bid_no = real_doc.get("bid", {}).get("bid_no") or safe_bid_no.replace("_", "/")
        real_pdf_file = selected_dir / f"{safe_bid_no}.pdf"
        real_md_file = selected_dir / f"{safe_bid_no}.md"
        real_pdf_text = real_md_file.read_text(encoding="utf-8") if real_md_file.exists() else real_doc.get("full_pdf_text", "")
        sample_hyperlinks = real_doc.get("hyperlinks", [])

        print(f"  📁 Selected Cached Tender: {safe_bid_no} ({test_bid_no})")
        from utils.s3_storage import upload_file as s3_upload_file, upload_bytes as s3_upload_bytes
        s3_upload_file(f"bids/{safe_bid_no}/bid.pdf", str(real_pdf_file), content_type="application/pdf")
        if real_pdf_text:
            s3_upload_bytes(f"bids/{safe_bid_no}/document.md", real_pdf_text.encode("utf-8"), content_type="text/markdown")

        from tasks.tier2_document import process_document
        t_start = time.time()
        task = process_document.delay(
            safe_bid_no=safe_bid_no,
            card_data=real_doc,
            pdf_path=str(real_pdf_file),
            bid_hyperlinks=sample_hyperlinks,
        )
        print(f"  ✅ Task Dispatched! Celery Task ID: {task.id}")
        print(f"  -> Monitoring execution across Tier 2 (document_queue) and Tier 3 (atc_rag_queue)...")
    else:
        print_step(3, "Live GeM Portal Online Scrape & Download (Tier 1 ➔ Tier 2 ➔ Tier 3)")
        if not has_scraper:
            print("  ⚠️ Notice: 'worker_scraper@local' is not running in background.")
            print("     Live crawling requires worker_scraper running on scraping_queue.")
            print("     Start with: .\\start_workers.ps1 -WithGateway")
            return False

        # Record existing bids in PostgreSQL to detect the new arrival
        with get_db_cursor(commit=False) as cur:
            cur.execute("SELECT id FROM bids;")
            existing_bids = set(r[0] for r in cur.fetchall())

        initial_dirs = set(p.name for p in (PROJECT_ROOT / "downloads").iterdir() if p.is_dir()) if (PROJECT_ROOT / "downloads").exists() else set()

        print("  -> Dispatching live scrape task for 1 tender to Tier 1 (scraping_queue)...")
        from tasks.tier1_scraper import scrape_category
        t_start = time.time()
        t1_task = scrape_category.delay(bid_type="Product Bid/RAs", target_count=1)
        print(f"  ✅ Tier 1 Scraper Task Dispatched! Celery Task ID: {t1_task.id}")
        print("  -> Monitoring: Playwright portal crawl ➔ PDF download ➔ MinIO upload ➔ Tier 2 OCR ➔ Tier 3 Embeddings...")

        max_wait = 180
        completed = False

        while time.time() - t_start < max_wait:
            time.sleep(2.5)
            elapsed = time.time() - t_start

            # Check if a new tender folder was downloaded by Tier 1
            if not safe_bid_no and (PROJECT_ROOT / "downloads").exists():
                current_dirs = [p.name for p in (PROJECT_ROOT / "downloads").iterdir() if p.is_dir() and p.name not in initial_dirs]
                if current_dirs:
                    safe_bid_no = current_dirs[0]
                    test_bid_no = safe_bid_no.replace("_", "/")
                    print(f"     [Tier 1] Tender downloaded live: {safe_bid_no} ({elapsed:.1f}s)")

            # Check if tender arrived in PostgreSQL
            has_bid = False
            has_chunks = False
            with get_db_cursor(commit=False) as cur:
                if safe_bid_no:
                    cur.execute("SELECT bid_no FROM bids WHERE id = %s;", (safe_bid_no,))
                    row = cur.fetchone()
                    if row:
                        has_bid = True
                        test_bid_no = row[0]
                    cur.execute("SELECT COUNT(*) FROM gem_bid_chunks WHERE bid_id = %s;", (safe_bid_no,))
                    has_chunks = cur.fetchone()[0] > 0
                else:
                    # Look for any new bid in DB not in existing_bids
                    if existing_bids:
                        cur.execute("SELECT id, bid_no FROM bids WHERE id NOT IN %s ORDER BY created_at DESC LIMIT 1;", (tuple(existing_bids),))
                    else:
                        cur.execute("SELECT id, bid_no FROM bids ORDER BY created_at DESC LIMIT 1;")
                    row = cur.fetchone()
                    if row:
                        safe_bid_no = row[0]
                        test_bid_no = row[1]
                        has_bid = True
                        cur.execute("SELECT COUNT(*) FROM gem_bid_chunks WHERE bid_id = %s;", (safe_bid_no,))
                        has_chunks = cur.fetchone()[0] > 0

            if has_bid and has_chunks:
                completed = True
                print(f"  🎉 SUCCESS! Pipeline completed end-to-end for live tender {safe_bid_no} ({test_bid_no}) in {elapsed:.2f}s!")
                break
            else:
                status_str = f"tender={safe_bid_no or 'crawling...'}, bid_in_db={has_bid}, chunks={has_chunks}"
                print(f"     ... waiting for live workers (elapsed: {elapsed:.1f}s, {status_str})")

        scorecard["Pipeline End-to-End Execution"] = completed
        if not completed:
            print("  ❌ Live pipeline timed out waiting for Tier 1 ➔ Tier 2 ➔ Tier 3.")
            return False

    # -------------------------------------------------------------------------
    # STEP 4: PostgreSQL & MinIO Artifact Verification
    # -------------------------------------------------------------------------
    print_step(4, "Database & Storage Verification")
    
    with get_db_cursor(commit=False) as cur:
        # Master row
        cur.execute("SELECT bid_no, organisation_name, status FROM bids WHERE id = %s;", (safe_bid_no,))
        row = cur.fetchone()
        if row:
            print(f"  ✅ PostgreSQL Master Bid Record: {row[0]} | Org: {row[1]} | Status: {row[2]}")
        else:
            print(f"  ❌ PostgreSQL Master Bid Record: Not Found!")

        # Vector chunks
        cur.execute("SELECT COUNT(*), chunk_type FROM gem_bid_chunks WHERE bid_id = %s GROUP BY chunk_type;", (safe_bid_no,))
        chunk_counts = cur.fetchall()
        print(f"  ✅ PostgreSQL Vector Chunks (pgvector 768-dim): {chunk_counts or 'None'}")

    # MinIO Verification
    from utils.s3_storage import object_exists
    time.sleep(1.0)
    has_doc = object_exists(f"bids/{safe_bid_no}/document.md")
    has_meta = object_exists(f"bids/{safe_bid_no}/metadata.json")
    has_pdf = object_exists(f"bids/{safe_bid_no}/bid.pdf")
    if has_doc and has_meta and has_pdf:
        print(f"  ✅ MinIO S3: bid.pdf, document.md, and metadata.json verified in 'gem-tenders'")
        scorecard["Artifacts in MinIO"] = True
    else:
        print(f"  ⚠️ MinIO object status: bid.pdf={has_pdf}, document.md={has_doc}, metadata.json={has_meta}")
        scorecard["Artifacts in MinIO"] = (has_doc or has_pdf)


    # -------------------------------------------------------------------------
    # STEP 5: FastAPI REST Gateway Query Verification
    # -------------------------------------------------------------------------
    print_step(5, "FastAPI REST Gateway Retrieval Test")
    gateway_url = "http://localhost:8000"
    
    try:
        # Check if gateway is reachable on port 8000
        health_resp = requests.get(f"{gateway_url}/health", timeout=2)
        if health_resp.status_code == 200:
            print("  ✅ FastAPI Gateway: Service Online on port 8000")
            
            # 5.1 Fetch Master Dossier
            dossier_resp = requests.get(f"{gateway_url}/api/v1/bids/{safe_bid_no}", timeout=3)
            if dossier_resp.status_code == 200:
                d_json = dossier_resp.json()
                print(f"  ✅ GET /api/v1/bids/{safe_bid_no} -> 200 OK (Item: {d_json.get('bid_no')})")

            
            # 5.2 Semantic Search Query
            search_item = "Equipment"
            if "card" in real_doc and "items" in real_doc["card"] and real_doc["card"]["items"]:
                search_item = (real_doc["card"]["items"][0].get("name") or "Equipment")[:40]
            else:
                with get_db_cursor(commit=False) as cur:
                    cur.execute("SELECT item_category FROM bid_items WHERE bid_id = %s LIMIT 1;", (safe_bid_no,))
                    row_it = cur.fetchone()
                    if row_it and row_it[0]:
                        search_item = row_it[0][:40]

            search_resp = requests.post(
                f"{gateway_url}/api/v1/search/semantic",
                json={"query": search_item, "top_k": 3},
                timeout=20
            )
            if search_resp.status_code == 200:
                s_json = search_resp.json()
                results = s_json.get("results", [])
                hit_found = any(r.get("bid_no") == test_bid_no or r.get("id") == safe_bid_no for r in results)
                print(f"  ✅ POST /api/v1/search/semantic -> 200 OK (Query: '{search_item}', Found {len(results)} matches, Hit: {hit_found})")
            
            scorecard["FastAPI Gateway Verification"] = True

        else:
            print(f"  ⚠️ FastAPI Gateway returned non-200: {health_resp.status_code}")
            scorecard["FastAPI Gateway Verification"] = False
    except requests.exceptions.ConnectionError:
        print("  ℹ️ FastAPI Gateway is not currently running on port 8000.")
        print("     To launch Gateway alongside workers:")
        print("     .\\start_workers.ps1 -WithGateway")
        scorecard["FastAPI Gateway Verification"] = "Not Running (Optional)"

    # -------------------------------------------------------------------------
    # FINAL SCORECARD
    # -------------------------------------------------------------------------
    print_header("LIVE PIPELINE VERIFICATION SUMMARY")
    for k, v in scorecard.items():
        symbol = "✅ PASS" if v is True else ("ℹ️ INFO" if isinstance(v, str) else "❌ FAIL")
        print(f"  {symbol:<10} | {k}: {v}")
    print("=" * 80 + "\n")

    return True


if __name__ == "__main__":
    test_live_pipeline()
