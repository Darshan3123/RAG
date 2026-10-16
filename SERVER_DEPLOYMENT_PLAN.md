# 🏛️ GeMBridge: Finalized Production Server Architecture, Resource Sizing & Worker Deployment Plan

> **Document Reference:** `SERVER_DEPLOYMENT_PLAN.md`  
> **Target Production Host:** Hostinger KVM 4 VPS (`srv1701681`) — Ubuntu 24.04 LTS (AMD EPYC 9355P, 16 GB RAM, 200 GB NVMe)  
> **Co-Existing Server Workload:** 46 Active Docker Containers (Dokploy, Traefik, Supabase Suite, PostgreSQL 17 pgvector, Redis, MinIO)  
> **Local Development OS:** Windows 10/11 (with Docker Desktop / WSL 2)  
> **Document Version:** 2.0.0 — Production & Local Hybrid Standard  

---

## 📑 Table of Contents

1. [Executive Blueprint: System Architecture](#1-executive-blueprint-system-architecture)
2. [Server Sizing & Hardware Resource Ceiling (Hostinger KVM 4)](#2-server-sizing--hardware-resource-ceiling-hostinger-kvm-4)
3. [Worker Queues & End-to-End Process Flow](#3-worker-queues--end-to-end-process-flow)
4. [Windows OS Local Development vs. Production Linux Deployment](#4-windows-os-local-development-vs-production-linux-deployment)
5. [Complete Environment Variables Specification (`.env`)](#5-complete-environment-variables-specification-env)
6. [Database (v3.0 Schema) & MinIO Object Storage Integration](#6-database-v30-schema--minio-object-storage-integration)
7. [FastAPI Gateway & Celery Synergy](#7-fastapi-gateway--celery-synergy)
8. [Docker Compose Specifications (Local Dev & Dokploy Production)](#8-docker-compose-specifications-local-dev--dokploy-production)
9. [Operational Runbook & CLI Execution Guide](#9-operational-runbook--cli-execution-guide)

---

## 1. Executive Blueprint: System Architecture

The **GeMBridge Data Engine** is an enterprise-grade procurement pipeline designed to run 24/7 without degrading host server stability. It decouples high-RAM browser automation, cloud API calls, and local CPU vector embeddings into an asynchronous **3-tier Celery queue** connected via **Redis 7**, orchestrated by **Celery Beat** on a 30-minute interval, persisted into **PostgreSQL 16/17** (with `pgvector`) and server-hosted **MinIO** object storage, and fronted by a high-speed **FastAPI** gateway.

```mermaid
flowchart TD
    subgraph Scheduler_Layer ["⏰ Schedule & Message Broker"]
        Beat["Celery Beat Scheduler\n(Clock daemon firing every 30m)"] -->|Dispatches Category Crawl Tasks| Redis[("Redis 7 Message Broker\n(Task Queues & Unacknowledged Buffer)")]
    end

    subgraph Tier1 ["Tier 1: Portal Crawling (scraping_queue)"]
        Redis -->|Pulls Crawl Task| WScraper["Playwright Crawler Workers (2 Concurrency)\n• Navigates bidplus.gem.gov.in\n• Downloads Bid & RA PDFs to in-memory buffer\n• Streams raw PDFs directly to MinIO\n• Enqueues document processing task\n• Frees browser in ~6s!"]
    end

    subgraph Tier2 ["Tier 2: Document OCR & Structuring (document_queue)"]
        Redis -->|Pulls Processing Task| WProcessor["Document Processing Workers (2 Concurrency)\n• PyMuPDF Selective Slicing (<0.2s, ₹0 cost)\n• Mistral Cloud OCR API (~7s)\n• Hybrid Markdown Stitching & Regex Normalizer\n• Uploads document.md & metadata.json to MinIO\n• Upserts Tender into PostgreSQL (v3.0 Schema)\n• Enqueues ATC & Vectorization task"]
    end

    subgraph Tier3 ["Tier 3: AI Compliance & Embeddings (atc_rag_queue)"]
        Redis -->|Pulls AI/Vector Task| WATC["ATC & Vector Workers (2 Concurrency)\n• Google Gemini 2.5 Flash 8-Domain Audit (~4s)\n• Streams atc_compliance.md & INFER_OUTPUT.json to MinIO\n• Inserts clauses into PostgreSQL checklist tables\n• BGE-base-en-v1.5 Dense Embeddings (~6s)\n• Inserts 768-dim Vectors into PostgreSQL (pgvector HNSW)"]
    end

    subgraph Storage_Layer ["🪣 Server-Hosted MinIO Object Storage (Bucket: 'gem-tenders')"]
        MinIO[("MinIO S3 Service\n• bids/{bid_no}/bid.pdf\n• bids/{bid_no}/ra.pdf\n• bids/{bid_no}/document.md\n• bids/{bid_no}/atc_compliance.md")]
        WScraper -->|Streams Raw PDFs| MinIO
        WProcessor -->|Streams Markdowns| MinIO
        WATC -->|Streams Compliance Reports| MinIO
    end

    subgraph Database_Layer ["🐘 PostgreSQL 16/17 (v3.0 Hybrid Schema in pgAdmin)"]
        Postgres[("PostgreSQL Database\n──────────────────────────────\n1. Table: bids (Scalars + TEXT[] + raw_data JSONB)\n2. Table: bid_items, bid_consignees, bid_schedules\n3. Table: bid_atc_checklist_items & physical_submissions\n4. Table: bid_terms (1:1 Decoupled Heavy Markdown)\n5. Table: gem_bid_chunks (vector(768) + HNSW)")]
        WProcessor -->|Upserts Bids & Items| Postgres
        WATC -->|Inserts Clauses & Vectors| Postgres
        pgAdmin["pgAdmin 4 GUI Console\n(Inspect tables, verify JSONB, query vectors)"] <--> Postgres
    end

    subgraph Gateway_Layer ["⚡ Fast Engine API Gateway (FastAPI)"]
        FastAPIGateway["FastAPI Service (Port 8000)\n• Swagger UI (/docs) for external developers\n• Sub-5ms async JSON queries\n• Streaming AI responses for RAG\n• S3 Presigned URL Redirection for PDFs\n• Dispatches on-demand Celery jobs via Redis"]
        Postgres <--> FastAPIGateway
        MinIO <-->|Generates Presigned S3 URLs| FastAPIGateway
        FastAPIGateway -.->|On-Demand Scrape Tasks| Redis
    end

    subgraph Consumer_Layer ["🌐 External Consumers & Telemetry"]
        WebPortal["Vendor Web Portal (Django + Next.js)"]
        MobileApp["Mobile App & Analytics Engine"]
        FlowerDashboard["Flower Dashboard (Port 5555)\n(Real-time Celery Worker Telemetry)"]

        FastAPIGateway <-->|REST API /docs| WebPortal
        FastAPIGateway <-->|REST API /docs| MobileApp
        Redis <--> FlowerDashboard
    end
```

---

## 2. Server Sizing & Hardware Resource Ceiling (Hostinger KVM 4)

From our empirical benchmark report ([`HOSTINGER_KVM4_BENCHMARK_AND_DEPLOYMENT_REPORT.md`](file:///c:/Projects/GeM/Scrapper%20&%20RAG%20Pipeline/Documentation/HOSTINGER_KVM4_BENCHMARK_AND_DEPLOYMENT_REPORT.md)), our VPS server (`srv1701681`) runs **46 active Docker containers** consuming **8.5 GB out of 16 GB RAM** with an ambient CPU load of **1.0 to 1.65**.

To eliminate the risk of Linux kernel Out-Of-Memory (OOM) termination and CPU throttling, the pipeline operates under strictly enforced hardware ceilings.

### 2.1 Concurrency & Memory Budget Summary

$$\text{Optimal Worker Concurrency} = \mathbf{6\text{ Total Workers}}$$

```
┌─────────────────────────────────────┬──────────────┬──────────────┬──────────────┐
│ Worker Tier & Queue                 │ Concurrency  │ RAM / Worker │ Total Memory │
├─────────────────────────────────────┼──────────────┼──────────────┼──────────────┤
│ Tier 1: Scraper (`scraping_queue`)   │ 2 Workers    │ ~400 MB      │ ~800 MB      │
│ Tier 2: OCR/Doc (`document_queue`)   │ 2 Workers    │ ~200 MB      │ ~400 MB      │
│ Tier 3: ATC/RAG (`atc_rag_queue`)    │ 2 Workers    │ ~450 MB      │ ~900 MB      │
│ Celery Beat (Scheduler Daemon)      │ 1 Daemon     │ ~60 MB       │ ~60 MB       │
├─────────────────────────────────────┼──────────────┼──────────────┼──────────────┤
│ TOTAL PIPELINE RUNTIME FOOTPRINT    │ 6 Processes  │ —            │ ~2.16 GB RAM │
└─────────────────────────────────────┴──────────────┴──────────────┴──────────────┘
```

### 2.2 Host Hardening Guarantees
1. **4 GB Swap Cushion:** A permanent `/swapfile` of 4,096 MB is active on the host, preventing sudden memory spikes from triggering `SIGKILL` (exit code 137).
2. **CPU Ceiling:** Hard-capped at **`cpus: '2.0'`** in Docker. The scraper can never consume more than 2 vCPUs, guaranteeing that **2 full vCPUs remain 100% free** for Supabase, Traefik, and Dokploy.
3. **RAM Ceiling:** Hard memory ceiling at **`memory: 3500M`** (3.5 GB). Operating at ~2.16 GB leaves over 1.3 GB of safety buffer before Docker limits are reached.
4. **Shared Memory Partition (`shm_size: 2gb`):** Chromium writes IPC buffers to `/dev/shm`. Expanding Docker's default 64 MB to 2 GB prevents browser bus errors under concurrent loads.
5. **Zombie Process Reaping (`init: true`):** Playwright continually spawns and tears down Chromium tabs. Docker's built-in Tini init system automatically reaps zombie child PIDs.

---

## 3. Worker Queues & End-to-End Process Flow

### 3.1 Tier 1: Scraper & Portal Crawler (`scraping_queue`)
* **Role:** Playwright headless Chromium browser crawler.
* **Responsibilities:**
  1. Spawns stealth Chromium instances with randomized User-Agents and real screen viewports.
  2. Traverses `bidplus.gem.gov.in/all-bids` or queries targeted tender numbers.
  3. Extracts card DOM attributes (`bid_no`, `ra_no`, `card_dates`, `card.departments`, `card.items`).
  4. Checks Redis cache `gem:seen:{bid_no}`. If already scraped and unchanged, skips in < 1ms.
  5. Downloads Bid PDF and RA PDF directly into an in-memory `io.BytesIO` buffer (**no disk I/O**).
  6. Streams the buffer to MinIO bucket `gem-tenders` under `bids/{bid_no}/bid.pdf`.
  7. Enqueues `task_process_document(bid_no, s3_key, card_meta)` into Redis `document_queue`.
  8. **Immediately releases the browser** to process the next card (~6s per tender).
  9. Recycles Chromium contexts every 20 tenders to flush V8/Blink memory caches.

### 3.2 Tier 2: Document Processing & OCR (`document_queue`)
* **Role:** High-speed document slicing, cloud OCR client, and relational database loader.
* **Responsibilities:**
  1. Pulls raw PDF stream from MinIO into memory.
  2. Scans `page.get_links()` via PyMuPDF to extract all clickable external URLs, BOQs, and specs.
  3. **Selective PDF Slicing:** Extracts digital front pages (1..N) via PyMuPDF in < 0.2s at **₹0 cost**. Slices out only the custom scanned Buyer Added ATC annexures into a temporary sub-PDF.
  4. Calls **Mistral Cloud OCR API** (`mistral-ocr-3-0`) on the sliced annexure (~7s).
  5. Merges digital text with Mistral Markdown and injects extracted hyperlinks.
  6. Regex parses 17 GFR sections (consignees, schedules, EMD/ePBG, relaxations, dates).
  7. Streams `bids/{bid_no}/document.md` and `metadata.json` to MinIO.
  8. **Database Milestone (PostgreSQL v3.0 Schema):**
     - Upserts master tender into `bids` (scalars + `required_documents TEXT[]` + `raw_data JSONB`).
     - Inserts line items into `bid_items` (with `specifications JSONB`).
     - Inserts delivery locations into `bid_consignees`.
     - Inserts lot schedules into `bid_evaluation_schedules`.
     - Inserts raw Markdown into `bid_terms`.
     - *At this milestone (T+16s), the tender is 100% visible and queryable on the web dashboard and REST API.*
  9. Enqueues `task_atc_and_embed(bid_no)` into Redis `atc_rag_queue`.

### 3.3 Tier 3: AI Compliance & Embeddings (`atc_rag_queue`)
* **Role:** AI compliance checklist extraction and semantic vector embedding.
* **Responsibilities:**
  1. Checks `buyer_atc_text` from PostgreSQL. If no buyer clauses exist, marks `atc_status = 'skipped_no_atc'` and jumps straight to vectorization.
  2. Calls **Google Gemini 2.5 Flash** with the 8-domain prompt rulebook (`Prompt.txt`) in a single-shot context (~4s).
  3. Extracts compliance clauses across 7 text domains and structured physical submissions (EMD DD, samples, PBG).
  4. Streams `bids/{bid_no}/atc_compliance.md` and `INFER_OUTPUT.json` to MinIO.
  5. Inserts compliance rules into `bid_atc_checklist_items` (with full-text search index).
  6. Inserts physical instruments into `bid_atc_physical_submissions`.
  7. Updates `bid_atc_analyses` with latency, tokens, and cost telemetry.
  8. **Vectorization:** Chunks tender text by domain (`item`, `compliance`, `general_pdf`), passes chunks through `BAAI/bge-base-en-v1.5` (held warm in RAM), and bulk-inserts 768-dim vectors into `gem_bid_chunks` with HNSW cosine similarity.
  9. *At this milestone (T+26s), the tender is 100% indexed for semantic RAG question-answering.*

### 3.4 Celery Beat Scheduler Daemon
* **Role:** Ultra-lightweight background clock daemon (~60 MB RAM).
* **Responsibilities:** Fires a single periodic trigger `task_dispatch_periodic_crawl.delay()` every **30 minutes**, enqueuing category crawl tasks to Redis without consuming CPU.

---

## 4. Windows OS Local Development vs. Production Linux Deployment

> [!WARNING]
> ### ⚠️ The Microsoft Windows Celery Concurrency Pitfall
> On Windows operating systems, Python does **not** support the POSIX `os.fork()` system call. Consequently:
> * Running Celery with the default `prefork` process pool on native Windows causes crashes, freezing, or errors like `ValueError: not enough values to unpack`.
> * On native Windows, Celery workers typically only function in **`solo` mode** (`--pool=solo`), which restricts each worker process to handling only 1 task at a time sequentially, eliminating true concurrency.
> * Thread pools (`--pool=threads` or `gevent`) often suffer from event-loop conflicts with Playwright's synchronous Chromium drivers.

To resolve this, we adopt a **Dual-Mode Strategy**:

```
┌─────────────────────────────────────────────────────────────┬─────────────────────────────────────────────────────────────┐
│ 🐳 Mode 1: Local Docker Compose (RECOMMENDED FOR LOCAL DEV) │ 💻 Mode 2: Native Windows OS (SOLO MODE / RAPID DEBUGGING)  │
├─────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ • Runs Redis, Celery Workers, Beat, & FastAPI inside Docker  │ • Runs Redis via standalone container                       │
│ • Uses Linux containers (WSL 2 backend)                     │ • Runs Celery workers directly in PowerShell using -P solo  │
│ • Full prefork multi-worker concurrency (6 workers)         │ • Restricts each worker to solo execution                   │
│ • 100% identical environment to production VPS               │ • Ideal for isolated script debugging and unit tests        │
└─────────────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────────┘
```

### 4.1 Running Locally with Docker (Recommended)
Running through Docker on Windows (via Docker Desktop with WSL 2) gives you true Linux `prefork` multi-worker concurrency with zero Windows-specific bugs:

```powershell
# 1. Navigate to project root
cd "c:\Projects\GeM\Scrapper & RAG Pipeline"

# 2. Build and launch all services (Redis, Workers, Beat, FastAPI)
docker compose -f docker-compose.local.yml up --build
```

### 4.2 Running Locally on Native Windows (PowerShell Solo Fallback)
If developing outside Docker on native Windows, run Redis via Docker and spawn each Celery worker explicitly specifying `-P solo`:

```powershell
# 1. Start Redis in Docker (one-liner)
docker run -d --name gem-local-redis -p 6379:6379 redis:7-alpine

# 2. Activate virtual environment
.\venv\Scripts\activate

# 3. Terminal 1: Start Tier 1 Scraper Worker (Solo Mode)
celery -A tasks.celery_app worker -Q scraping_queue -l info -P solo -n scraper_worker@%h

# 4. Terminal 2: Start Tier 2 Document Worker (Solo Mode)
celery -A tasks.celery_app worker -Q document_queue -l info -P solo -n doc_worker@%h

# 5. Terminal 3: Start Tier 3 ATC & RAG Worker (Solo Mode)
celery -A tasks.celery_app worker -Q atc_rag_queue -l info -P solo -n atc_worker@%h

# 6. Terminal 4: Start Celery Beat Scheduler Daemon
celery -A tasks.celery_app beat -l info

# 7. Terminal 5: Start FastAPI Gateway
uvicorn gateway.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 5. Complete Environment Variables Specification (`.env`)

```env
# ==============================================================================
# GeMBridge Engine — Unified Environment Configuration
# ==============================================================================

# ── 1. REDIS & CELERY BROKER ──────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# ── 2. POSTGRESQL & PGVECTOR DATABASE ─────────────────────────────────────────
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=gem_db
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_postgres_password_here
DATABASE_URL=postgresql://postgres:your_postgres_password_here@localhost:5432/gem_db

# ── 3. MINIO OBJECT STORAGE (S3-Compatible) ───────────────────────────────────
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=gem-tenders
MINIO_SECURE=false

# ── 4. WORKER CONCURRENCY & SCHEDULING ────────────────────────────────────────
MAX_CONCURRENT_WORKERS=6
SCRAPE_INTERVAL_MINUTES=30
MAX_RETRIES_PER_BID=3
RETRY_DELAY_SECONDS=10

# ── 5. CLOUD OCR & PARSER ENGINES ─────────────────────────────────────────────
OCR_PROVIDER=mistral
MISTRAL_API_KEY=your_mistral_api_key_here
ENABLE_PDF_ATC_SPLIT=true

# ── 6. AI COMPLIANCE & LLM CREDENTIALS ────────────────────────────────────────
ATC_LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
GEMINI_THINKING_LEVEL=low
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini

# ── 7. RAG EMBEDDINGS & CROSS-ENCODER ─────────────────────────────────────────
RAG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
RAG_RERANKER_MODEL=BAAI/bge-reranker-base
RAG_USE_RERANKER=true
RAG_TOP_K=5
HF_TOKEN=your_huggingface_token_here

# ── 8. ANTI-BOT DELAYS & PORTAL SETTINGS ──────────────────────────────────────
GEM_BASE_URL=https://bidplus.gem.gov.in
TARGET_PER_TYPE=5
MAX_EMPTY_PAGES=3
PAGE_LOAD_WAIT_MIN=4
PAGE_LOAD_WAIT_MAX=8
BETWEEN_CARDS_WAIT_MIN=1
BETWEEN_CARDS_WAIT_MAX=3
```

---

## 6. Database (v3.0 Schema) & MinIO Object Storage Integration

### 6.1 Database Architecture (`ER-Diagram-V3.md`)
The system unifies all relational tender columns, native PostgreSQL arrays, JSONB payloads, and vector embeddings into a cohesive schema:
* **`bids` (Master Table):** Queryable scalars (dates, value, EMD, status, department) + `required_documents TEXT[]` + complete `raw_data JSONB`.
* **`bid_items`:** 1:N line items with `specifications JSONB` and Trigram fuzzy search index (`gin_trgm_ops`).
* **`bid_consignees`:** 1:N delivery locations with `pincode CHAR(6)` index and `quantity_raw TEXT` for lumpsum contracts.
* **`bid_evaluation_schedules`:** 1:N lot-wise schedules with `grouped_items JSONB` for nested group tenders.
* **`bid_atc_checklist_items`:** 1:N compliance rules across 7 domains with full-text search index (`tsvector`).
* **`bid_atc_physical_submissions`:** 1:N offline instruments (samples, DDs, PBGs).
* **`bid_hyperlinks`:** 1:N extracted clickable URLs.
* **`bid_terms`:** 1:1 decoupled storage for heavy full-text Markdown.
* **`bid_atc_analyses`:** 1:1 telemetry tracking latency, token usage, and AI execution costs.
* **`gem_bid_chunks`:** 1:N semantic vector store with 768-dim embeddings and HNSW cosine distance index (`<=>`).

### 6.2 MinIO Object Storage Key Structure
Bucket: `gem-tenders` (Private access; files accessed via presigned URLs):
```
gem-tenders/
 └── bids/
      └── {bid_no}/
           ├── bid.pdf                 (Original Portal Tender Document)
           ├── ra.pdf                  (Reverse Auction PDF, if present)
           ├── document.md             (OCR Parsed Full Markdown)
           ├── metadata.json           (Normalized Structured JSON)
           ├── atc_compliance.md       (5-Section AI Compliance Checklist)
           └── INFER_OUTPUT.json       (Raw LLM Inference Response)
```

---

## 7. FastAPI Gateway & Celery Synergy

The FastAPI gateway operates on **port 8000**, exposing high-speed endpoints to external web applications and background dispatchers:

```mermaid
flowchart LR
    Client["External Web / Mobile App"] --> Gateway["FastAPI Service (Port 8000)"]
    Gateway -->|Sub-5ms Query| DB[("PostgreSQL 16")]
    Gateway -->|Presigned S3 URL Redirect| S3[("MinIO Storage")]
    Gateway -->|Dispatch Scrape Task in 3ms| Redis[("Redis 7 Broker")]
    Redis --> Workers["Celery Worker Queues"]
```

### 7.1 Key Endpoints
1. **`GET /api/v1/bids`:** Paginated tender search with scalar filters (`department`, `estimated_value`, `closing_date`, `status`). Responds in < 5ms.
2. **`GET /api/v1/bids/{bid_no}`:** Returns tender scalar metadata, full `raw_data JSONB`, and parsed compliance checklists.
3. **`GET /api/v1/bids/{bid_no}/pdf`:** Issues an HTTP 307 redirect to a time-limited (24-hour) MinIO S3 Presigned URL, offloading file download bandwidth from the application server.
4. **`POST /api/v1/bids/ask`:** Natural language semantic RAG query executing cosine similarity search against `gem_bid_chunks` with cross-encoder reranking.
5. **`POST /api/v1/bids/scrape-ondemand`:** Dispatches an immediate scrape job to Celery via Redis in ~3ms, returning a `task_id` for background status polling.

---

## 8. Docker Compose Specifications

### 8.1 Production Stack (`docker-compose.prod.yml`) — For Dokploy & Hostinger KVM 4

```yaml
version: '3.8'

services:
  # ── 1. REDIS MESSAGE BROKER ─────────────────────────────────────────────────
  redis:
    image: redis:7-alpine
    container_name: gem-engine-redis
    restart: unless-stopped
    command: redis-server --appendonly yes --maxmemory 512mb --maxmemory-policy noeviction
    volumes:
      - gem_redis_data:/data
    networks:
      - gem_network

  # ── 2. TIER 1: PLAYWRIGHT SCRAPER WORKER ─────────────────────────────────────
  worker-scraper:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: gem-worker-scraper
    restart: unless-stopped
    command: celery -A tasks.celery_app worker -Q scraping_queue -c 2 -l info -n scraper_worker@%h
    init: true
    shm_size: '2gb'
    env_file: .env
    depends_on:
      - redis
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 1200M
    networks:
      - gem_network

  # ── 3. TIER 2: DOCUMENT PROCESSING & OCR WORKER ──────────────────────────────
  worker-document:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: gem-worker-document
    restart: unless-stopped
    command: celery -A tasks.celery_app worker -Q document_queue -c 2 -l info -n doc_worker@%h
    env_file: .env
    depends_on:
      - redis
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 600M
    networks:
      - gem_network

  # ── 4. TIER 3: ATC COMPLIANCE & VECTOR WORKER ───────────────────────────────
  worker-atc:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: gem-worker-atc
    restart: unless-stopped
    command: celery -A tasks.celery_app worker -Q atc_rag_queue -c 2 -l info -n atc_worker@%h
    env_file: .env
    depends_on:
      - redis
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 1200M
    networks:
      - gem_network

  # ── 5. CELERY BEAT SCHEDULER DAEMON ──────────────────────────────────────────
  celery-beat:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: gem-celery-beat
    restart: unless-stopped
    command: celery -A tasks.celery_app beat -l info
    env_file: .env
    depends_on:
      - redis
    deploy:
      resources:
        limits:
          cpus: '0.1'
          memory: 150M
    networks:
      - gem_network

  # ── 6. FASTAPI REST GATEWAY ──────────────────────────────────────────────────
  fastapi-gateway:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: gem-fastapi-gateway
    restart: unless-stopped
    command: uvicorn gateway.main:app --host 0.0.0.0 --port 8000 --workers 2
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - redis
    deploy:
      resources:
        limits:
          cpus: '0.4'
          memory: 350M
    networks:
      - gem_network

  # ── 7. FLOWER QUEUE MONITORING DASHBOARD ─────────────────────────────────────
  flower:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: gem-flower-telemetry
    restart: unless-stopped
    command: celery -A tasks.celery_app flower --port=5555
    ports:
      - "5555:5555"
    env_file: .env
    depends_on:
      - redis
    networks:
      - gem_network

networks:
  gem_network:
    name: gem_engine_network

volumes:
  gem_redis_data:
    name: gem_redis_data
```

### 8.2 Local Development Stack (`docker-compose.local.yml`) — For Windows Docker Desktop

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    container_name: gem-local-redis
    ports:
      - "6379:6379"

  worker-scraper:
    build: .
    command: celery -A tasks.celery_app worker -Q scraping_queue -c 2 -l info
    init: true
    shm_size: '2gb'
    env_file: .env
    depends_on:
      - redis
    volumes:
      - .:/app

  worker-document:
    build: .
    command: celery -A tasks.celery_app worker -Q document_queue -c 2 -l info
    env_file: .env
    depends_on:
      - redis
    volumes:
      - .:/app

  worker-atc:
    build: .
    command: celery -A tasks.celery_app worker -Q atc_rag_queue -c 2 -l info
    env_file: .env
    depends_on:
      - redis
    volumes:
      - .:/app

  celery-beat:
    build: .
    command: celery -A tasks.celery_app beat -l info
    env_file: .env
    depends_on:
      - redis
    volumes:
      - .:/app

  fastapi-gateway:
    build: .
    command: uvicorn gateway.main:app --host 0.0.0.0 --port 8000 --reload
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - redis
    volumes:
      - .:/app
```

---

## 9. Operational Runbook & CLI Execution Guide

### 9.1 Local Testing Commands (Windows PowerShell)

```powershell
# Run Celery Beat manually (Dry Run check):
celery -A tasks.celery_app beat --loglevel=debug

# Inspect active Celery queues via CLI:
celery -A tasks.celery_app inspect active

# Trigger an immediate on-demand crawl of a specific tender:
curl -X POST "http://localhost:8000/api/v1/bids/scrape-ondemand" -H "Content-Type: application/json" -d '{"bid_no": "GEM/2026/B/8019323"}'

# Test Semantic RAG search endpoint:
curl -X POST "http://localhost:8000/api/v1/bids/ask" -H "Content-Type: application/json" -d '{"query": "What are the EMD requirements and past experience turnover?", "top_k": 3}'
```

### 9.2 Hostinger Production Management Commands (`srv1701681`)

```bash
# Check status of all engine containers:
docker ps --filter "name=gem-"

# Inspect real-time CPU and Memory consumption across all workers:
docker stats gem-worker-scraper gem-worker-document gem-worker-atc gem-fastapi-gateway

# View streaming logs of the Scraper worker:
docker logs -f gem-worker-scraper

# View live Flower queue telemetry:
# Open browser at: http://srv1701681:5555
```
