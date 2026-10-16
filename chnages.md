# 🛠️ GeMBridge Codebase Gap Analysis & Migration Specification

> **Document Reference:** `chnages.md`  
> **Target Production Architecture:** As defined in [`SERVER_DEPLOYMENT_PLAN.md`](file:///F:/Projects/gem_scraper/SERVER_DEPLOYMENT_PLAN.md)  
> **Target Database Schema:** As defined in [`ER-Diagram-V3.md`](file:///F:/Projects/gem_scraper/Documentation/ER-Diagram-V3.md)  
> **Target Host:** Hostinger KVM 4 VPS (`srv1701681`) — Ubuntu 24.04 LTS (16 GB RAM, 4 vCPUs)  
> **Status:** Codebase Audit & Gap Analysis  

---

## 📑 Table of Contents

1. [Executive Codebase Gap Analysis](#1-executive-codebase-gap-analysis)
2. [Master Inventory: File Change Classification](#2-master-inventory-file-change-classification)
3. [Group A: New Files to Create](#3-group-a-new-files-to-create)
4. [Group B: Existing Files to Modify & Refactor](#4-group-b-existing-files-to-modify--refactor)
5. [Group C: Existing Files to Keep Unchanged (Reusable Assets)](#5-group-c-existing-files-to-keep-unchanged-reusable-assets)
6. [Group D: Deprecated or Legacy Files](#6-group-d-deprecated-or-legacy-files)
7. [Dependency Updates (`requirements.txt` & `.env`)](#7-dependency-updates-requirementstxt--env)
8. [Step-by-Step Phased Execution Roadmap](#8-step-by-step-phased-execution-roadmap)

---

## 1. Executive Codebase Gap Analysis

The current repository is built as a **synchronous single-process monolith** (`main.py` -> `pipeline/scraper.py`). It downloads files to local disk folders (`downloads/<bid_no>/`) and stores records in a flat SQLite table (`storage/gem_bids.db`) alongside a local ChromaDB directory (`storage/chroma_db`).

To achieve the 24/7 background microservice platform defined in `SERVER_DEPLOYMENT_PLAN.md`, the codebase must transition from **local-disk file management** to **distributed asynchronous worker queues with PostgreSQL v3.0 and MinIO S3 object storage**.

### Architecture Evolution Matrix

| Architectural Dimension | Current Codebase State | Target Production State (`SERVER_DEPLOYMENT_PLAN.md`) | Gap Severity |
| :--- | :--- | :--- | :---: |
| **Execution Model** | Single-threaded sequential Python CLI | Distributed 3-Tier Celery workers on Redis 7 | 🔴 High |
| **Database** | SQLite (`gem_bids.db`) with 18 flat text columns | PostgreSQL 16/17 (10-table v3.0 hybrid schema with `JSONB`) | 🔴 High |
| **Document Storage** | Local disk folders (`downloads/{bid_no}/*.pdf`) | MinIO S3 Bucket (`gem-tenders/bids/{bid_no}/...`) | 🔴 High |
| **Semantic AI / RAG** | Local ChromaDB on disk (`storage/chroma_db`) | PostgreSQL `pgvector` (`gem_bid_chunks` with HNSW index) | 🟡 Medium |
| **API & Access Layer** | None (CLI terminal output only) | FastAPI async REST Gateway on Port 8000 | 🔴 High |
| **Containerization** | None (Runs directly in Windows/Linux shell) | Docker Compose (Local Dev & Dokploy Production) | 🔴 High |
| **Core Parser & OCR** | PyMuPDF + Mistral OCR + Normalizer regex | Fully functional, high-accuracy modular components | 🟢 Reusable |
| **ATC Compliance Engine** | Gemini 2.5 Flash 8-domain prompt rulebook | Fully functional single-shot extraction module | 🟢 Reusable |

---

## 2. Master Inventory: File Change Classification

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 📁 SUMMARY OF CODEBASE ACTIONS                                                         │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 🟢 NEW FILES TO CREATE (12 Files):                                                     │
│    1. storage/postgres_db.py              (PostgreSQL v3.0 connection & upsert engine) │
│    2. storage/init_v3_schema.sql          (SQL DDL for 10 tables, indexes, pgvector)   │
│    3. utils/s3_storage.py                 (MinIO S3 upload, streaming, presigned URLs) │
│    4. tasks/celery_app.py                 (Celery instance, Redis broker, queue routes)│
│    5. tasks/tier1_scraper.py              (Tier 1 worker: Crawl, buffer PDF, MinIO)   │
│    6. tasks/tier2_document.py             (Tier 2 worker: OCR, parse, PostgreSQL upsert│
│    7. tasks/tier3_atc_rag.py              (Tier 3 worker: Gemini ATC, BGE embeddings)  │
│    8. tasks/beat_schedule.py              (Celery Beat 30-min recurring clock daemon)  │
│    9. gateway/main.py                     (FastAPI REST Gateway entrypoint, port 8000) │
│   10. gateway/routes/bids.py              (Tender search, details, S3 presigned PDF)   │
│   11. Dockerfile                          (Multi-stage Docker build for workers & API) │
│   12. docker-compose.prod.yml             (Production stack for Dokploy/Hostinger VPS) │
│   13. docker-compose.local.yml            (Local Windows Docker Desktop dev stack)     │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 🟡 EXISTING FILES TO MODIFY (5 Files):                                                 │
│    1. config/settings.py                  (Add Redis, PostgreSQL, MinIO, Celery vars)  │
│    2. requirements.txt                    (Add celery, redis, psycopg2, minio, fastapi)│
│    3. .env.example / .env                 (Declare new service credentials)            │
│    4. core/browser.py                     (Add in-memory PDF download buffer stream)   │
│    5. rag/vector_store.py                 (Add pgvector upsert & cosine search adapter)│
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 🟢 EXISTING FILES TO KEEP AS-IS (Modular Core Engines):                                │
│    • core/parser.py                       (High-accuracy 17-section GFR regex parser)  │
│    • core/normalizer.py                   (Currency, date, and validation normalizer)  │
│    • core/pdf_splitter.py                 (PyMuPDF selective front-page/ATC boundary)  │
│    • core/mistral_ocr_manager.py          (Mistral cloud OCR client)                   │
│    • pipeline/atc_analyzer.py             (Gemini 2.5 Flash 8-domain compliance engine)│
│    • utils/logger.py & utils/antibot.py   (Logging & humanized browser behavior)       │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 🔴 DEPRECATED / LEGACY FILES (To Replace Gradually):                                   │
│    • storage/database.py                  (Replaced by storage/postgres_db.py)         │
│    • storage/gem_bids.db                  (Legacy SQLite database)                     │
│    • main.py                              (CLI loop replaced by Celery Beat & FastAPI) │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Group A: New Files to Create

### 1. `storage/init_v3_schema.sql`
* **Purpose:** Single idempotent SQL script creating the complete 10-table relational schema, constraints, B-Tree/GIN/HNSW indexes, and `vector` / `pg_trgm` extensions defined in [`ER-Diagram-V3.md`](file:///F:/Projects/gem_scraper/Documentation/ER-Diagram-V3.md).
* **Location:** `storage/init_v3_schema.sql`
* **Key Components:**
  * Extensions: `CREATE EXTENSION IF NOT EXISTS vector;`, `CREATE EXTENSION IF NOT EXISTS pg_trgm;`
  * Tables: `bids`, `bid_items`, `bid_consignees`, `bid_evaluation_schedules`, `bid_atc_checklist_items`, `bid_atc_physical_submissions`, `bid_hyperlinks`, `bid_terms`, `bid_atc_analyses`, `gem_bid_chunks`.

### 2. `storage/postgres_db.py`
* **Purpose:** High-performance database client module using `psycopg2.pool.ThreadedConnectionPool` or `asyncpg` to execute ACID transactions and upserts.
* **Location:** `storage/postgres_db.py`
* **Functions to Implement:**
  * `init_db()`: Executes `init_v3_schema.sql` to initialize tables if not present.
  * `upsert_tender(bid_data: dict) -> bool`: Inserts/updates `bids` (scalar fields + `required_documents TEXT[]` + `raw_data JSONB`), `bid_items`, `bid_consignees`, `bid_evaluation_schedules`, and `bid_terms` in a single database transaction.
  * `save_atc_results(bid_no: str, atc_data: dict)`: Inserts categorized clauses into `bid_atc_checklist_items`, offline requirements into `bid_atc_physical_submissions`, and logs telemetry in `bid_atc_analyses`.
  * `insert_chunks(bid_no: str, chunks: list[dict])`: Bulk-inserts 768-dim embeddings into `gem_bid_chunks`.
  * `get_bid_by_no(bid_no: str) -> dict`: Returns complete structured tender data for the REST API.

### 3. `utils/s3_storage.py`
* **Purpose:** MinIO / AWS S3 client wrapper for zero-disk in-memory PDF streaming and presigned download URL generation.
* **Location:** `utils/s3_storage.py`
* **Functions to Implement:**
  * `get_s3_client()`: Returns authenticated MinIO client using `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`.
  * `ensure_bucket_exists(bucket_name: str)`: Creates `gem-tenders` bucket on first boot.
  * `upload_bytes(key: str, data: bytes, content_type: str)`: Streams in-memory PDF/Markdown bytes directly to MinIO.
  * `download_bytes(key: str) -> bytes`: Pulls file stream from MinIO into memory for Tier 2 worker.
  * `get_presigned_url(key: str, expiry_hours: int = 24) -> str`: Generates signed download URL for web clients.

### 4. `tasks/celery_app.py`
* **Purpose:** Celery application factory configuring message broker connection, result backend, serialization, task routing, and worker settings.
* **Location:** `tasks/celery_app.py`
* **Configuration:**
  * Broker: `redis://localhost:6379/0`
  * Queues:
    * `scraping_queue` -> routes `tasks.crawl_*`
    * `document_queue` -> routes `tasks.process_document`
    * `atc_rag_queue` -> routes `tasks.atc_and_embed`
  * Settings: `task_acks_late=True`, `worker_prefetch_multiplier=1`, `task_reject_on_worker_lost=True`.

### 5. `tasks/tier1_scraper.py`
* **Purpose:** Tier 1 Celery task wrapper for Playwright crawling.
* **Location:** `tasks/tier1_scraper.py`
* **Workflow:**
  * Pulls task from `scraping_queue`.
  * Launches Playwright context, extracts card metadata, checks Redis deduplication key (`gem:seen:{bid_no}`).
  * Downloads Bid PDF to `io.BytesIO` buffer.
  * Calls `s3_storage.upload_bytes("bids/{bid_no}/bid.pdf", buffer)`.
  * Dispatches `task_process_document.delay(bid_no, card_meta)` to `document_queue`.
  * Closes browser page (~6s runtime).

### 6. `tasks/tier2_document.py`
* **Purpose:** Tier 2 Celery task wrapper for document OCR and relational database ingestion.
* **Location:** `tasks/tier2_document.py`
* **Workflow:**
  * Pulls task from `document_queue`.
  * Downloads `bid.pdf` stream from MinIO into memory.
  * Performs PyMuPDF selective slicing (digital pages vs. scanned ATC annexures).
  * Calls Mistral Cloud OCR on scanned annexures.
  * Calls `core.parser.parse_bid_data()` and `core.normalizer.normalize_bid_data()`.
  * Uploads `document.md` and `metadata.json` to MinIO.
  * Calls `postgres_db.upsert_tender()` to store records across `bids`, `bid_items`, `bid_consignees`, and `bid_terms`.
  * Dispatches `task_atc_and_embed.delay(bid_no)` to `atc_rag_queue`.
  * *Tender is now 100% visible on the web portal at T+16s.*

### 7. `tasks/tier3_atc_rag.py`
* **Purpose:** Tier 3 Celery task wrapper for AI compliance extraction and pgvector embeddings.
* **Location:** `tasks/tier3_atc_rag.py`
* **Workflow:**
  * Pulls task from `atc_rag_queue`.
  * Reads `buyer_atc_text` from PostgreSQL.
  * Calls Gemini 2.5 Flash for 8-domain compliance check (`pipeline/atc_analyzer.py`).
  * Uploads `atc_compliance.md` and `INFER_OUTPUT.json` to MinIO.
  * Calls `postgres_db.save_atc_results()` to insert checklist and physical submission items.
  * Chunks text and embeds via BGE-base-en-v1.5.
  * Inserts vectors into `gem_bid_chunks` via `postgres_db.insert_chunks()`.
  * *Tender is now 100% indexed for RAG at T+26s.*

### 8. `tasks/beat_schedule.py`
* **Purpose:** Celery Beat periodic scheduler configuration.
* **Location:** `tasks/beat_schedule.py`
* **Schedule:** Fires every 30 minutes, enqueuing category crawl tasks across all 9 GeM bid types to `scraping_queue`.

### 9. `gateway/main.py`
* **Purpose:** FastAPI entrypoint exposing Swagger docs on port 8000.
* **Location:** `gateway/main.py`
* **Features:** CORS middleware, healthcheck route (`/health`), API version prefix (`/api/v1`), exception handlers.

### 10. `gateway/routes/bids.py`
* **Purpose:** High-performance REST endpoints for frontend applications.
* **Location:** `gateway/routes/bids.py`
* **Endpoints:**
  * `GET /api/v1/bids`: Paginated search with filters (status, department, value, dates). Executes in < 5ms.
  * `GET /api/v1/bids/{bid_no}`: Complete tender details, items, consignees, and compliance checklist.
  * `GET /api/v1/bids/{bid_no}/pdf`: Returns HTTP 307 redirect to presigned MinIO S3 URL.
  * `POST /api/v1/bids/ask`: Semantic RAG question-answering endpoint.
  * `POST /api/v1/bids/scrape-ondemand`: Enqueues immediate Celery scrape task for a specific bid number.

### 11. `Dockerfile`
* **Purpose:** Multi-stage production container image.
* **Location:** `Dockerfile`
* **Components:** Python 3.12-slim, system packages, Playwright Chromium dependencies, installed requirements, non-root user execution.

### 12. `docker-compose.prod.yml` & `docker-compose.local.yml`
* **Purpose:** Multi-container orchestration configurations.
* **Location:** `docker-compose.prod.yml` (Production: Dokploy on Hostinger KVM 4) and `docker-compose.local.yml` (Local Windows dev with WSL 2).
* **Services:** `redis`, `worker-scraper`, `worker-document`, `worker-atc`, `celery-beat`, `fastapi-gateway`, `flower`.

---

## 4. Group B: Existing Files to Modify & Refactor

### 1. `config/settings.py`
* **Current State:** Loads SQLite paths and local ChromaDB paths.
* **Changes Needed:**
  * Add Redis connection settings (`REDIS_URL`, `CELERY_BROKER_URL`).
  * Add PostgreSQL connection settings (`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL`).
  * Add MinIO connection settings (`MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`, `MINIO_SECURE`).
  * Add worker concurrency and Celery task settings (`MAX_CONCURRENT_WORKERS=6`, `SCRAPE_INTERVAL_MINUTES=30`).

### 2. `requirements.txt`
* **Current State:** Contains Playwright, PyMuPDF, Mistral, Gemini, ChromaDB.
* **Changes Needed:** Add the distributed stack dependencies:
  ```txt
  # Distributed Queues & Message Broker
  celery[redis]>=5.3.6
  redis>=5.0.3
  flower>=2.0.1

  # PostgreSQL & Vector Database
  psycopg2-binary>=2.9.9
  pgvector>=0.2.5

  # Object Storage (S3 / MinIO)
  minio>=7.2.5

  # REST API Gateway
  fastapi>=0.111.0
  uvicorn[standard]>=0.29.0
  pydantic>=2.7.0
  ```

### 3. `.env` and `.env.example`
* **Current State:** Contains only Mistral/Gemini API keys and anti-bot timing.
* **Changes Needed:** Append complete production configuration blocks for Redis, PostgreSQL, and MinIO as documented in `SERVER_DEPLOYMENT_PLAN.md` Section 5.

### 4. `core/browser.py`
* **Current State:** Saves downloaded PDFs directly to Windows disk paths via `download.save_as(filepath)`.
* **Changes Needed:**
  * Add `download_pdf_to_memory(url) -> io.BytesIO` method that reads PDF content into memory bytes.
  * This allows Tier 1 workers to stream directly to MinIO without touching local disk.

### 5. `rag/vector_store.py`
* **Current State:** Hardcoded to ChromaDB (`storage/chroma_db`).
* **Changes Needed:**
  * Add PostgreSQL `pgvector` adapter so generated BGE embeddings are inserted into `gem_bid_chunks`.
  * Update query function to execute cosine distance search (`<=>`) against `gem_bid_chunks`.

---

## 5. Group C: Existing Files to Keep Unchanged (Reusable Assets)

The following modules represent well-tested core logic and can be reused as-is:

* **`core/parser.py` (61 KB):** Fully implements the 17-section GFR tender parser. Compatible with the V3 schema.
* **`core/normalizer.py` (18 KB):** Handles currency cleaning, ISO date normalization, and data validation rules.
* **`core/pdf_splitter.py` (13 KB):** Handles PyMuPDF selective front-page slicing and ATC boundary detection.
* **`core/mistral_ocr_manager.py` (27 KB):** Handles Mistral cloud OCR requests, retry logic, and markdown formatting.
* **`pipeline/atc_analyzer.py` (36 KB):** Implements the 8-domain prompt rulebook with Gemini 2.5 Flash.
* **`utils/antibot.py`:** Provides randomized delays and human-like browsing jitter.
* **`utils/logger.py`:** Structured console and file logging.
* **`utils/pdf_hyperlinks.py`:** PyMuPDF hyperlink URI extraction.

---

## 6. Group D: Deprecated or Legacy Files

* **`storage/database.py`:** SQLite-specific storage with 18 flat text columns. Replaced by `storage/postgres_db.py`.
* **`storage/gem_bids.db` & `storage/gem_bids.json`:** Legacy local SQLite database. Kept temporarily as fallback until PostgreSQL v3.0 ingestion is verified.
* **`main.py` CLI scraping loop:** Replaced by Celery Beat scheduler daemon and FastAPI on-demand endpoints. `main.py` will be retained as an offline administrative utility script for manual backfills and diagnostics.

---

## 7. Dependency Updates (`requirements.txt` & `.env`)

### Packages to Add to `requirements.txt`
```txt
# ── Distributed Worker & Message Broker ──────────────────────
celery[redis]>=5.3.6
redis>=5.0.3
flower>=2.0.1

# ── PostgreSQL & Vector Engine ───────────────────────────────
psycopg2-binary>=2.9.9
pgvector>=0.2.5

# ── MinIO / S3 Object Storage ────────────────────────────────
minio>=7.2.5

# ── FastAPI REST Gateway ─────────────────────────────────────
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
pydantic>=2.7.0
```

### Keys to Add to `.env`
```env
# REDIS & BROKER
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# POSTGRESQL & PGVECTOR
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=gem_db
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password_here
DATABASE_URL=postgresql://postgres:your_password_here@localhost:5432/gem_db

# MINIO S3 OBJECT STORAGE
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=gem-tenders
MINIO_SECURE=false

# CONCURRENCY CEILINGS
MAX_CONCURRENT_WORKERS=6
SCRAPE_INTERVAL_MINUTES=30
```

---

## 8. Step-by-Step Phased Execution Roadmap

### Phase 1: Database & Storage Engine (Foundation)
1. **Create `storage/init_v3_schema.sql`:** DDL definitions for the 10 V3 tables, constraints, and indexes.
2. **Create `storage/postgres_db.py`:** Connection pooling and transactional upsert functions.
3. **Verify with 61 Existing Bids:** Ingest all 61 existing JSON files from `downloads/` into PostgreSQL to verify schema integrity.
4. **Create `utils/s3_storage.py`:** MinIO client for in-memory upload/download and presigned URLs.

### Phase 2: Distributed Celery Worker Queues (The Pipeline)
1. **Update `requirements.txt` & `config/settings.py`:** Install dependencies and load environment variables.
2. **Create `tasks/celery_app.py`:** Configure broker, result backend, and task routing.
3. **Refactor Browser In-Memory Download (`core/browser.py`):** Add memory streaming for PDFs.
4. **Implement Worker Tasks:**
   * `tasks/tier1_scraper.py` (Crawl -> MinIO)
   * `tasks/tier2_document.py` (OCR -> PostgreSQL v3)
   * `tasks/tier3_atc_rag.py` (Gemini ATC -> pgvector)
5. **Configure `tasks/beat_schedule.py`:** 30-minute periodic crawl dispatcher.

### Phase 3: REST API Gateway
1. **Create `gateway/main.py`:** FastAPI application on port 8000.
2. **Create `gateway/routes/bids.py`:** Fast listing, detail, S3 presigned PDF, and on-demand scrape endpoints.
3. **Integrate RAG Chat Endpoint:** Natural language semantic search powered by `gem_bid_chunks`.

### Phase 4: Containerization & Hostinger VPS Deployment
1. **Create `Dockerfile`:** Multi-stage image build.
2. **Create `docker-compose.local.yml`:** Local dev stack with WSL 2 / Docker Desktop.
3. **Create `docker-compose.prod.yml`:** Hard resource ceilings (`cpus: '2.0'`, `memory: 3500M`, `shm_size: 2gb`) for Dokploy deployment on Hostinger KVM 4.
4. **Verify Deployment with Flower:** Monitor real-time queue latency on port 5555.
