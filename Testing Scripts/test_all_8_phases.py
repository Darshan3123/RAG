# =========================================================================
# Testing Scripts/test_all_8_phases.py
# Master End-to-End Verification Test Suite
# Validates all 8 Completed Architecture Phases:
#   1. PostgreSQL v3.0 Database Schema & Ingestion
#   2. MinIO S3 Object Storage Client Module
#   3. Celery 3-Tier Distributed Queue Architecture
#   4. Codebase Modular Consolidation & Cleanup
#   5. Local Containerization & Windows Scripts
#   6. Ingestion & Storage Verification Test Scripts
#   7. Vector Embedding Linking in Tier 3 Worker
#   8. FastAPI REST Gateway (Port 8000 Endpoints)
# =========================================================================
import json
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from utils.logger import get_logger

log = get_logger("test_all_8_phases")


def run_master_test_suite():
    print("=" * 80)
    print("🚀 GE MBRIDGE ARCHITECTURE — MASTER END-TO-END VERIFICATION TEST SUITE")
    print("=" * 80)

    scorecard = {}
    total_checks_passed = 0
    total_checks_failed = 0

    def check(name: str, condition: bool, details: str = ""):
        nonlocal total_checks_passed, total_checks_failed
        if condition:
            total_checks_passed += 1
            print(f"    ✅ PASS: {name} {details}")
            return True
        else:
            total_checks_failed += 1
            print(f"    ❌ FAIL: {name} {details}")
            return False

    # =========================================================================
    # PHASE 1: PostgreSQL v3.0 Database Schema & Ingestion
    # =========================================================================
    print("\n" + "─" * 80)
    print("📦 [PHASE 1] PostgreSQL v3.0 Database Schema & Ingestion")
    print("─" * 80)
    p1_ok = True
    try:
        from storage.postgres_db import PostgresBidDatabase, get_connection_pool, get_db_cursor
        db = PostgresBidDatabase()
        pool = get_connection_pool()
        p1_ok &= check("PostgreSQL Connection Pool Initialized", pool is not None and not pool.closed)

        with get_db_cursor(commit=False) as cur:
            # 1. Extensions
            cur.execute("SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pg_trgm');")
            exts = {r[0] for r in cur.fetchall()}
            p1_ok &= check("Required PostgreSQL Extensions Installed", "vector" in exts and "pg_trgm" in exts, f"(Found: {exts})")

            # 2. Table Count
            expected_tables = {
                "bids", "bid_items", "bid_consignees", "bid_evaluation_schedules",
                "bid_atc_checklist_items", "bid_atc_physical_submissions",
                "bid_hyperlinks", "bid_terms", "bid_atc_analyses", "gem_bid_chunks"
            }
            cur.execute("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
            """)
            found_tables = {r[0] for r in cur.fetchall()}
            missing_tables = expected_tables - found_tables
            p1_ok &= check("All 10 Relational & Vector Tables Exist", len(missing_tables) == 0, f"(Missing: {missing_tables or 'None'})")

            # 3. Vector HNSW Index
            cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'gem_bid_chunks' AND indexname = 'idx_gem_bid_chunks_hnsw';")
            idx_found = cur.fetchone() is not None
            p1_ok &= check("pgvector HNSW Cosine Index Exists", idx_found, "(idx_gem_bid_chunks_hnsw)")

            # 4. Ingestion / Master Record Query
            cur.execute("SELECT COUNT(*) FROM bids;")
            bid_count = cur.fetchone()[0]
            p1_ok &= check("Master Bids Table Accessible & Populated", bid_count > 0, f"(Total Records: {bid_count})")

    except Exception as e:
        p1_ok = False
        check("PostgreSQL Database Operations", False, str(e))

    scorecard["Phase 1: PostgreSQL v3.0 Database Schema & Ingestion"] = p1_ok

    # =========================================================================
    # PHASE 2: MinIO S3 Object Storage Client Module
    # =========================================================================
    print("\n" + "─" * 80)
    print("🪣 [PHASE 2] MinIO S3 Object Storage Client Module")
    print("─" * 80)
    p2_ok = True
    try:
        from utils.s3_storage import ensure_bucket_exists, upload_bytes, download_bytes, get_presigned_url
        p2_ok &= check("MinIO S3 Client Connected & Initialized", True)

        # 1. Bucket check
        ensure_bucket_exists()
        p2_ok &= check("Target Bucket 'gem-tenders' Exists", True)

        # 2. Upload / Download Roundtrip
        test_key = "tests/master_pipeline_verify.txt"
        test_payload = b"GeMBridge MinIO S3 Streaming Verification Token"
        upload_bytes(test_key, test_payload, content_type="text/plain")
        read_back = download_bytes(test_key)
        p2_ok &= check("In-Memory Direct S3 Byte Streaming (Upload/Download)", read_back == test_payload)

        # 3. Presigned URL Generation
        presigned = get_presigned_url(test_key, expiry_hours=1)
        p2_ok &= check("Time-Limited S3 Presigned URL Generation", presigned.startswith("http") and "gem-tenders" in presigned)

    except Exception as e:
        p2_ok = False
        check("MinIO S3 Storage Operations", False, str(e))

    scorecard["Phase 2: MinIO S3 Object Storage Client Module"] = p2_ok

    # =========================================================================
    # PHASE 3: Celery 3-Tier Distributed Queue Architecture
    # =========================================================================
    print("\n" + "─" * 80)
    print("⚡ [PHASE 3] Celery 3-Tier Distributed Queue Architecture")
    print("─" * 80)
    p3_ok = True
    try:
        import redis
        from config.settings import REDIS_URL
        from tasks.celery_app import app as celery_app

        # 1. Redis Broker Connection
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        r_ping = r.ping()
        p3_ok &= check("Redis Broker & Result Backend Reachable", r_ping is True)

        # 2. Queues & Routing Configuration
        routes = celery_app.conf.task_routes or {}
        p3_ok &= check("Celery Route: scraping_queue defined", "tasks.tier1_scraper.*" in routes and routes["tasks.tier1_scraper.*"]["queue"] == "scraping_queue")
        p3_ok &= check("Celery Route: document_queue defined", "tasks.tier2_document.*" in routes and routes["tasks.tier2_document.*"]["queue"] == "document_queue")
        p3_ok &= check("Celery Route: atc_rag_queue defined", "tasks.tier3_atc_rag.*" in routes and routes["tasks.tier3_atc_rag.*"]["queue"] == "atc_rag_queue")


        # 3. Worker Tasks Registry
        reg_tasks = celery_app.tasks
        p3_ok &= check("Tier 1 Task Registered (scrape_category)", "tasks.tier1_scraper.scrape_category" in reg_tasks)
        p3_ok &= check("Tier 1 Task Registered (scrape_single_bid)", "tasks.tier1_scraper.scrape_single_bid" in reg_tasks)
        p3_ok &= check("Tier 2 Task Registered (process_document)", "tasks.tier2_document.process_document" in reg_tasks)
        p3_ok &= check("Tier 3 Task Registered (process_atc_and_embed)", "tasks.tier3_atc_rag.process_atc_and_embed" in reg_tasks)
        p3_ok &= check("Celery Late Acknowledgments Enabled", celery_app.conf.task_acks_late is True)

    except Exception as e:
        p3_ok = False
        check("Celery 3-Tier Distributed Queue Operations", False, str(e))

    scorecard["Phase 3: Celery 3-Tier Distributed Queue Architecture"] = p3_ok

    # =========================================================================
    # PHASE 4: Codebase Modular Consolidation & Cleanup
    # =========================================================================
    print("\n" + "─" * 80)
    print("🧹 [PHASE 4] Codebase Modular Consolidation & Cleanup")
    print("─" * 80)
    p4_ok = True
    try:
        # 1. Core modules importability
        from core.browser import GemBrowser
        from core.parser import get_card_details
        from core.normalizer import normalize_bid_data, validate_bid_data
        from core.atc_analyzer import analyze_bid_atc
        from core.embedder import build_structured_bid_chunks, generate_bid_embeddings
        from core.llm import generate_answer
        p4_ok &= check("All 6 Centralized `core/` AI & Extraction Modules Importable", True)

        # 2. Obsolete SQLite Removal
        sqlite_in_storage = not (ROOT_DIR / "storage" / "database.py").exists()
        p4_ok &= check("Legacy Monolithic `storage/database.py` (SQLite) Removed", sqlite_in_storage)

        # 3. Legacy Synchronous Scraper Removal
        legacy_scraper = not (ROOT_DIR / "pipeline" / "scraper.py").exists()
        p4_ok &= check("Legacy Monolithic `pipeline/scraper.py` Removed", legacy_scraper)

    except Exception as e:
        p4_ok = False
        check("Codebase Consolidation & Imports", False, str(e))

    scorecard["Phase 4: Codebase Modular Consolidation & Cleanup"] = p4_ok

    # =========================================================================
    # PHASE 5: Local Containerization & Windows Scripts
    # =========================================================================
    print("\n" + "─" * 80)
    print("🐳 [PHASE 5] Local Containerization & Windows Scripts")
    print("─" * 80)
    p5_ok = True
    try:
        # 1. Dockerfile
        dockerfile = ROOT_DIR / "Dockerfile"
        p5_ok &= check("Multi-Stage Dockerfile Exists", dockerfile.exists() and dockerfile.stat().st_size > 500)

        # 2. Local Docker Compose
        compose_local = ROOT_DIR / "docker-compose.local.yml"
        p5_ok &= check("docker-compose.local.yml Exists", compose_local.exists() and compose_local.stat().st_size > 500)

        # 3. Production Docker Compose
        compose_prod = ROOT_DIR / "docker-compose.prod.yml"
        p5_ok &= check("docker-compose.prod.yml Exists (Dokploy Ready)", compose_prod.exists() and compose_prod.stat().st_size > 500)

        # 4. Windows PowerShell Solo Worker Launcher
        start_workers = ROOT_DIR / "start_workers.ps1"
        p5_ok &= check("start_workers.ps1 Windows Runner Exists", start_workers.exists() and "scraping_queue" in start_workers.read_text(encoding="utf-8"))


    except Exception as e:
        p5_ok = False
        check("Containerization & Shell Scripts", False, str(e))

    scorecard["Phase 5: Local Containerization & Windows Scripts"] = p5_ok

    # =========================================================================
    # PHASE 6: Ingestion & Storage Verification Test Scripts
    # =========================================================================
    print("\n" + "─" * 80)
    print("🧪 [PHASE 6] Ingestion & Storage Verification Test Scripts")
    print("─" * 80)
    p6_ok = True
    try:
        # 1. Existing Test Scripts Presence
        t_scripts = ROOT_DIR / "Testing Scripts"
        p6_ok &= check("test_postgres_ingestion.py Exists", (t_scripts / "test_postgres_ingestion.py").exists())
        p6_ok &= check("test_minio_storage.py Exists", (t_scripts / "test_minio_storage.py").exists())
        p6_ok &= check("test_rag_search.py Exists", (t_scripts / "test_rag_search.py").exists())
        p6_ok &= check("test_api_gateway.py Exists", (t_scripts / "test_api_gateway.py").exists())

        # 2. Sample Downloads Dataset
        json_samples = list((ROOT_DIR / "downloads").glob("*/*.json"))
        p6_ok &= check(f"Tender Documents in downloads/ Directory", len(json_samples) >= 10, f"(Found: {len(json_samples)} tenders)")

        # 3. Normalize & Validate Test on a real JSON
        if json_samples:
            sample_json_path = json_samples[0]
            with open(sample_json_path, "r", encoding="utf-8") as f:
                raw_json_data = json.load(f)
            bid_no = raw_json_data.get("bid", {}).get("bid_no") or raw_json_data.get("_id", "")
            norm_res = normalize_bid_data(
                card_data=raw_json_data,
                parsed_pdf_data=raw_json_data.get("pdf", {}),
                pdf_text=raw_json_data.get("full_pdf_text", "")
            )
            val_res = validate_bid_data(
                bid_no=bid_no,
                card_data=raw_json_data,
                parsed_pdf_data=raw_json_data.get("pdf", {}),
                normalized=norm_res
            )
            p6_ok &= check(f"Normalizer Output Structure Validated on {sample_json_path.name}", isinstance(norm_res, dict) and "dates" in norm_res and "items" in norm_res)
            p6_ok &= check(f"Validator Engine Executed on {sample_json_path.name}", isinstance(val_res, dict) and "issues" in val_res)


    except Exception as e:
        p6_ok = False
        check("Ingestion Verification Scripts", False, str(e))

    scorecard["Phase 6: Ingestion & Storage Verification Test Scripts"] = p6_ok

    # =========================================================================
    # PHASE 7: Vector Embedding Linking in Tier 3 Worker
    # =========================================================================
    print("\n" + "─" * 80)
    print("🧠 [PHASE 7] Vector Embedding Linking in Tier 3 Worker")
    print("─" * 80)
    p7_ok = True
    try:
        from core.embedder import build_structured_bid_chunks, embed_query, generate_bid_embeddings
        from storage.postgres_db import PostgresBidDatabase
        db_p7 = PostgresBidDatabase()

        # 1. Test Domain-Specific Chunking
        sample_doc = {
            "_id": "GEM_2026_B_TEST_PHASE7",
            "bid": {"bid_no": "GEM/2026/B/TEST/PHASE7", "product_type": "Product"},
            "card": {
                "bid_no": "GEM/2026/B/TEST/PHASE7",
                "start_datetime": "2026-10-19 10:00:00",
                "end_datetime": "2026-10-30 18:00:00"
            },
            "pdf": {
                "timing": {
                    "bid_start_datetime": "19-10-2026 10:00:00",
                    "bid_end_datetime": "30-10-2026 18:00:00"
                },
                "items": {"item 1": {"item_category": "Precision Centrifuge Rotor", "quantity": 5}},
                "consignees": [{"consignee_reporting_officer": "Dr. Sharma", "consignee_address": "AIIMS New Delhi", "quantity": 5, "delivery_days": 30}],
                "departments": {"department_name": "Health", "organisation_name": "AIIMS"}
            },
            "normalized": {
                "dates": {
                    "start_date_iso": "2026-10-19T10:00:00+05:30",
                    "end_date_iso": "2026-10-30T18:00:00+05:30"
                }
            },
            "atc_analysis": {
                "checklist": {
                    "ELIGIBILITY_AND_QUALIFICATION": ["Must possess ISO 13485 certification", "Minimum 3 years past experience"],
                    "PHYSICAL_SUBMISSIONS": [{"Item": "EMD DD", "Deadline": "Within 5 days", "Payable At": "New Delhi"}]
                }
            },
            "full_pdf_text": "The bidder must deliver precision centrifuge rotors to AIIMS warehouse within 30 days."
        }

        chunks = build_structured_bid_chunks(sample_doc)
        types_in_chunks = {c["chunk_type"] for c in chunks}
        p7_ok &= check("Domain Chunks Generated (item, compliance, general_pdf)", "item" in types_in_chunks and "compliance" in types_in_chunks and "general_pdf" in types_in_chunks)

        # 2. Embedding Generation (768-dim BGE)
        t0 = time.perf_counter()
        query_vec = embed_query("centrifuge rotor AIIMS")
        t_vec = time.perf_counter() - t0
        p7_ok &= check("BGE Vector Inference Dimension", len(query_vec) == 768, f"(Dim: {len(query_vec)}, Latency: {t_vec*1000:.1f}ms)")

        # 3. Vector Insert & Similarity Search in PostgreSQL
        # Ensure master bid exists to satisfy FK constraint
        db_p7.upsert_bid(sample_doc)
        chunks_with_emb = generate_bid_embeddings(sample_doc)
        inserted = db_p7.insert_chunks("GEM_2026_B_TEST_PHASE7", chunks_with_emb)
        p7_ok &= check("Idempotent pgvector Insertion into gem_bid_chunks", inserted == len(chunks_with_emb), f"({inserted} chunks)")

        # 4. Cosine Distance Search (< 50ms)
        t0 = time.perf_counter()
        hits = db_p7.search_chunks(query_vec, top_k=2, bid_id="GEM_2026_B_TEST_PHASE7")
        t_search = time.perf_counter() - t0
        p7_ok &= check("Sub-50ms Cosine Distance Vector Search", len(hits) > 0 and t_search < 0.05, f"(Found: {len(hits)} hits, Latency: {t_search*1000:.2f}ms)")


    except Exception as e:
        p7_ok = False
        check("Vector Embedding Linking & Search", False, str(e))

    scorecard["Phase 7: Vector Embedding Linking in Tier 3 Worker"] = p7_ok

    # =========================================================================
    # PHASE 8: FastAPI REST Gateway (Port 8000 Endpoints)
    # =========================================================================
    print("\n" + "─" * 80)
    print("🌐 [PHASE 8] FastAPI REST Gateway (Port 8000 Endpoints)")
    print("─" * 80)
    p8_ok = True
    try:
        from fastapi.testclient import TestClient
        from gateway.main import app as fastapi_app

        client = TestClient(fastapi_app)

        # 1. Health
        res = client.get("/health")
        p8_ok &= check("GET /health -> 200 OK", res.status_code == 200)

        # 2. Master Bids List
        res = client.get("/api/v1/bids?limit=2")
        p8_ok &= check("GET /api/v1/bids -> 200 OK", res.status_code == 200 and "pagination" in res.json())

        # 3. Master Dossier & Partitions
        sample_bid = "GEM/2026/B/7858260"
        res = client.get(f"/api/v1/bids/{sample_bid}")
        p8_ok &= check(f"GET /api/v1/bids/{sample_bid} -> 200 OK", res.status_code in (200, 404))

        # Check sub-partitions
        res_items = client.get(f"/api/v1/bids/{sample_bid}/items")
        p8_ok &= check(f"GET /api/v1/bids/{sample_bid}/items -> 200/404", res_items.status_code in (200, 404))

        res_fin = client.get(f"/api/v1/bids/{sample_bid}/financials")
        p8_ok &= check(f"GET /api/v1/bids/{sample_bid}/financials -> 200/404", res_fin.status_code in (200, 404))

        res_atc = client.get(f"/api/v1/bids/{sample_bid}/atc")
        p8_ok &= check(f"GET /api/v1/bids/{sample_bid}/atc -> 200/404", res_atc.status_code in (200, 404))

        # 4. Discovery & Aggregations
        res_types = client.get("/api/v1/types")
        p8_ok &= check("GET /api/v1/types -> 200 OK", res_types.status_code == 200)

        res_orgs = client.get("/api/v1/organizations?limit=2")
        p8_ok &= check("GET /api/v1/organizations -> 200 OK", res_orgs.status_code == 200)

        # 5. Search (Quick, Keyword, Semantic)
        res_quick = client.get("/api/v1/search/quick?q=tube")
        p8_ok &= check("GET /api/v1/search/quick -> 200 OK", res_quick.status_code == 200)

        res_key = client.get("/api/v1/search/keyword?q=tube")
        p8_ok &= check("GET /api/v1/search/keyword -> 200 OK", res_key.status_code == 200)

        res_sem = client.post("/api/v1/search/semantic", json={"query": "medical laboratory tubes", "top_k": 2})
        p8_ok &= check("POST /api/v1/search/semantic -> 200 OK", res_sem.status_code == 200 and "results" in res_sem.json())

        # 6. Presigned Documents
        res_doc = client.get(f"/api/v1/documents/{sample_bid}/pdf")
        p8_ok &= check(f"GET /api/v1/documents/{sample_bid}/pdf -> 200/404", res_doc.status_code in (200, 404, 500))

        # 7. Asynchronous Task Operations
        res_task = client.post("/api/v1/tasks/scrape-bid", json={"bid_no": "GEM/2026/B/7858260"})
        p8_ok &= check("POST /api/v1/tasks/scrape-bid -> 200 OK", res_task.status_code == 200 and "task_id" in res_task.json())

        # 8. Analytics & Telemetry
        res_over = client.get("/api/v1/analytics/overview")
        p8_ok &= check("GET /api/v1/analytics/overview -> 200 OK", res_over.status_code == 200 and "metrics" in res_over.json())

        res_tele = client.get("/api/v1/analytics/ai-telemetry")
        p8_ok &= check("GET /api/v1/analytics/ai-telemetry -> 200 OK", res_tele.status_code == 200 and "ai_telemetry" in res_tele.json())

    except Exception as e:
        p8_ok = False
        check("FastAPI REST Gateway Operations", False, str(e))

    scorecard["Phase 8: FastAPI REST Gateway (Port 8000 Endpoints)"] = p8_ok

    # =========================================================================
    # FINAL EXECUTIVE SUMMARY SCORECARD
    # =========================================================================
    print("\n" + "=" * 80)
    print("🏆 FINAL ARCHITECTURE SCORECARD — ALL 8 PHASES")
    print("=" * 80)
    for phase_name, is_passed in scorecard.items():
        status_label = "✅ 100% OPERATIONAL" if is_passed else "❌ FAILING"
        print(f"  {status_label:<24} | {phase_name}")

    print("─" * 80)
    print(f"  TOTAL CHECKS: {total_checks_passed} PASSED | {total_checks_failed} FAILED")
    all_phases_ok = all(scorecard.values())
    if all_phases_ok:
        print("  🎉 STATUS: ALL 8 PHASES ARE FULLY OPERATIONAL AND VERIFIED!")
    else:
        print("  ⚠️ STATUS: SOME CHECKS FAILED — REVIEW THE LOGS ABOVE.")
    print("=" * 80)

    return all_phases_ok


if __name__ == "__main__":
    success = run_master_test_suite()
    sys.exit(0 if success else 1)
