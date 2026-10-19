# 🏗️ GeMBridge v3.0 — Enterprise Architecture & System Flow Diagrams

> **Architecture Standard:** v3.0.0 Production Enterprise Edition  
> **Target Infrastructure:** Ubuntu 24.04 LTS (Hostinger KVM 4 VPS: 4 vCPUs / 16 GB RAM) + Local Windows Dev  
> **Core Stack:** FastAPI Gateway (ASGI), 3-Tier Celery Workers, Redis 7 Broker, PostgreSQL 18 (`pgvector` & `pg_trgm`), MinIO S3 Object Storage, Traefik Reverse Proxy, Dokploy PaaS  
> **Last Verified:** 51 Automated Integration Checks — **100% Pass Rate**  

---

## 🗺️ 1. Global High-Level System Architecture

The following diagram illustrates the complete GeMBridge v3 distributed topology across all 5 operational layers:

```mermaid
flowchart TD
    subgraph CLIENTS ["1. Client & Consumption Layer"]
        REACT["Frontend React/Next.js Web Portal"]
        MOBILE["Mobile App Clients"]
        B2B["B2B Enterprise Data Feeds"]
        SWAGGER["Interactive Swagger UI (/docs)"]
    end

    subgraph GATEWAY ["2. REST API Gateway Layer (FastAPI Port 8000)"]
        AUTH["CORS & API Security Middleware"]
        TELEMETRY_MW["Request Latency & Telemetry Middleware"]
        
        subgraph ROUTERS ["API Router Modules (gateway/routes/)"]
            R_BIDS["routes/bids.py\n(Master Dossier & 10 Partitions)"]
            R_SEARCH["routes/search.py\n(Prefix, Trigram & pgvector Semantic)"]
            R_DOCS["routes/documents.py\n(MinIO S3 Presigned Streaming)"]
            R_DISC["routes/discovery.py\n(Types, Ministries, Departments)"]
            R_TASKS["routes/tasks.py\n(On-Demand Scrape Dispatches)"]
            R_ANALYTICS["routes/analytics.py\n(Pipeline KPIs & AI Token Audits)"]
            R_HEALTH["routes/health.py\n(DB, Redis, MinIO Deep Check)"]
        end
    end

    subgraph BROKER ["3. Message Broker & Distributed Queues (Redis 7)"]
        BEAT["Celery Beat Periodic Scheduler\n(Every 30 Mins Category Sweep)"]
        Q_SCRAPE["Redis Queue: scraping_queue\n(Playwright Web Crawler Jobs)"]
        Q_DOC["Redis Queue: document_queue\n(Slicing, Normalization & OCR Jobs)"]
        Q_ATC["Redis Queue: atc_rag_queue\n(Gemini ATC Analysis & pgvector Indexing)"]
        DEDUP["Redis Deduplication Store\n(gem:seen:{safe_bid_no} - 7 Days TTL)"]
    end

    subgraph WORKERS ["4. Distributed 3-Tier Queue Worker Layer"]
        subgraph T1 ["Tier 1: Web Scraper Worker"]
            PLAYWRIGHT["Playwright Chromium Stealth\n(2GB /dev/shm, Anti-Bot Jitter)"]
            INMEM_DL["Zero-Disk In-Memory PDF Capture"]
        end

        subgraph T2 ["Tier 2: Document & OCR Worker"]
            PYMUPDF["PyMuPDF Front-Page Slicer\n(<0.2s In-Memory Digital Parse)"]
            MISTRAL["Mistral Cloud OCR\n(Scanned Annexures Fallback)"]
            NORMALIZER["Core Normalizer & Validator\n(Lakhs/Crores -> Float, ISO Dates)"]
        end

        subgraph T3 ["Tier 3: ATC Compliance & AI Vector Worker"]
            GEMINI["Google Gemini 2.5 Flash\n(8-Domain ATC Legal Compliance Engine)"]
            EMBEDDER["BAAI/bge-base-en-v1.5 Embedder\n(768-dim Dense Vector Generation)"]
        end
    end

    subgraph PERSISTENCE ["5. Enterprise Hybrid Persistence Layer"]
        subgraph S3 ["MinIO S3 Object Storage (Bucket: gem-tenders)"]
            S3_PDF["bids/{bid_no}/bid.pdf (Raw Document)"]
            S3_MD["bids/{bid_no}/document.md (Parsed Text)"]
            S3_META["bids/{bid_no}/metadata.json (Full Schema)"]
            S3_ATC["bids/{bid_no}/atc_compliance.json (Checklist)"]
        end

        subgraph PG ["PostgreSQL 18 Hybrid Relational & Vector Database"]
            T_BIDS[("bids\n(Master Header, Dates, Scalars, raw_data JSONB)")]
            T_ITEMS[("bid_items\n(Line Items with specifications JSONB)")]
            T_CONSIGNEES[("bid_consignees\n(Locations, Officers, Pincodes, Quantities)")]
            T_SCHEDULES[("bid_evaluation_schedules\n(Multi-Lot Bidding Matrices)")]
            T_TERMS[("bid_terms\n(Payment, Delivery & Warranty Terms)")]
            T_HYPERLINKS[("bid_hyperlinks\n(Extracted PDF Hyperlinks)")]
            T_ATC[("bid_atc_checklist_items\n(8-Domain Legal Clauses)")]
            T_SUBM[("bid_atc_physical_submissions\n(Hardcopy DDs, Samples, Deadlines)")]
            T_TELEMETRY[("bid_atc_analyses\n(AI Token Costs & Mistral OCR Pages)")]
            T_CHUNKS[("gem_bid_chunks\n(768-dim Vectors + HNSW Cosine Index)")]
        end
    end

    %% Client -> Gateway
    CLIENTS --> AUTH --> TELEMETRY_MW --> ROUTERS

    %% Gateway -> Persistence & Broker
    R_BIDS --> T_BIDS & T_ITEMS & T_CONSIGNEES
    R_SEARCH --> T_CHUNKS
    R_DOCS -->|Generate 24h Presigned URL| S3
    R_TASKS -->|Dispatch delay()| Q_SCRAPE
    R_HEALTH --> PG & BROKER & S3

    %% Celery Flow
    BEAT -->|Cron trigger| Q_SCRAPE
    Q_SCRAPE --> T1
    T1 -->|Check Seen| DEDUP
    T1 -->|Stream PDF Bytes| S3_PDF
    T1 -->|Enqueue Tier 2| Q_DOC

    Q_DOC --> T2
    S3_PDF -->|Stream into Memory| PYMUPDF
    PYMUPDF -->|If Scanned| MISTRAL
    PYMUPDF & MISTRAL --> NORMALIZER
    NORMALIZER -->|Stream Artifacts| S3_MD & S3_META
    NORMALIZER -->|ACID Multi-Table Upsert| PG
    NORMALIZER -->|Enqueue Tier 3| Q_ATC

    Q_ATC --> T3
    S3_META -->|Read Context| GEMINI
    GEMINI -->|Extract 8 Domains| T_ATC & T_SUBM & T_TELEMETRY
    GEMINI -->|Stream JSON| S3_ATC
    T3 -->|Generate Chunks| EMBEDDER
    EMBEDDER -->|Bulk Insert Embeddings| T_CHUNKS
```

---

## ⚡ 2. End-to-End Data Lifecycle Sequence

The following sequence diagram details the exact asynchronous workflow when a new tender is processed from GeM portal discovery to vector retrieval:

```mermaid
sequenceDiagram
    autonumber
    participant Beat as Celery Beat / API Trigger
    participant T1 as Tier 1 Scraper Worker
    participant GeM as GeM Portal (Playwright)
    participant Redis as Redis 7 Broker
    participant MinIO as MinIO S3 (gem-tenders)
    participant T2 as Tier 2 Document Worker
    participant PG as PostgreSQL 18 (gem-bridge)
    participant T3 as Tier 3 ATC & RAG Worker
    participant Gemini as Gemini 2.5 Flash
    participant Gateway as FastAPI Gateway (:8000)
    participant User as Frontend Client / User

    %% STEP 1: Discovery & Scrape
    Note over Beat, GeM: Phase 1: Ingestion & Zero-Disk Stream
    Beat->>Redis: Enqueue scrape_category / scrape_single_bid
    Redis->>T1: Pop job from scraping_queue
    T1->>Redis: Check dedup key (gem:seen:{safe_bid_no})
    alt Tender already processed
        T1->>Redis: Skip tender (deduplication hit)
    else New Tender
        T1->>Redis: Set gem:seen:{safe_bid_no} = 'downloading' (7d TTL)
        T1->>GeM: Launch Chromium, apply category filter, extract card DOM
        T1->>GeM: Download PDF into memory bytes (Zero-Disk)
        T1->>MinIO: upload_bytes("bids/{bid_no}/bid.pdf", pdf_bytes)
        T1->>Redis: Enqueue process_document(safe_bid_no, card_data) to document_queue
    end

    %% STEP 2: Document Processing & ACID Upsert
    Note over T2, PG: Phase 2: PyMuPDF Slicing & ACID Ingestion
    Redis->>T2: Pop job from document_queue
    T2->>MinIO: download_bytes("bids/{bid_no}/bid.pdf")
    T2->>T2: PyMuPDF in-memory text & table extraction (<0.2s)
    opt If Scanned Image Annexures Found
        T2->>T2: Call Mistral Cloud OCR on scanned pages
    end
    T2->>T2: Run Core Normalizer (Lakhs/Crores -> Float, ISO-8601 timestamps)
    T2->>MinIO: upload_bytes("document.md") & upload_bytes("metadata.json")
    T2->>PG: BEGIN ACID TRANSACTION
    T2->>PG: Upsert bids, bid_items, bid_consignees, bid_terms, bid_schedules
    T2->>PG: COMMIT TRANSACTION
    T2->>Redis: Enqueue process_atc_and_embed(safe_bid_no) to atc_rag_queue

    %% STEP 3: ATC Compliance & pgvector
    Note over T3, PG: Phase 3: Gemini ATC & Vector Embeddings
    Redis->>T3: Pop job from atc_rag_queue
    T3->>Gemini: Send tender text + ATC annexures to 8-domain legal prompt
    Gemini-->>T3: Return 8-domain compliance checklist + physical submissions
    T3->>PG: Upsert bid_atc_checklist_items, bid_atc_physical_submissions, bid_atc_analyses
    T3->>MinIO: upload_bytes("atc_compliance.json")
    T3->>T3: Chunk text into Item, Compliance & General PDF passages
    T3->>T3: Generate 768-dim embeddings via local BGE model (CPU/GPU)
    T3->>PG: Bulk insert into gem_bid_chunks (Indexed by HNSW vector_cosine_ops)
    T3->>Redis: Set gem:seen:{safe_bid_no} = 'completed'

    %% STEP 4: Client Querying
    Note over User, Gateway: Phase 4: Sub-50ms API Retrieval
    User->>Gateway: POST /api/v1/search/semantic {"query": "centrifuge rotor 15ml"}
    Gateway->>Gateway: Vectorize query with local BGE model (768-dim)
    Gateway->>PG: SELECT * FROM gem_bid_chunks ORDER BY embedding <=> query_vector LIMIT 5
    PG-->>Gateway: Top matches returned in 3.4ms via HNSW index
    Gateway-->>User: JSON Response with similarity scores and matching tender chunks
```

---

## 🗄️ 3. PostgreSQL 18 Relational & Vector Schema (10 Tables)

The database schema is divided into **10 specialized relational and vector tables**, ensuring zero data duplication, strict foreign keys with cascading updates, and sub-millisecond query performance:

```mermaid
erDiagram
    bids ||--o{ bid_items : "contains line items"
    bids ||--o{ bid_consignees : "specifies delivery locations"
    bids ||--o{ bid_evaluation_schedules : "groups segmented lots"
    bids ||--o{ bid_terms : "defines legal clauses"
    bids ||--o{ bid_hyperlinks : "tracks parsed URIs"
    bids ||--o{ bid_atc_checklist_items : "8-domain compliance"
    bids ||--o{ bid_atc_physical_submissions : "offline DD/samples"
    bids ||--o{ bid_atc_analyses : "AI token telemetry"
    bids ||--o{ gem_bid_chunks : "768-dim vector embeddings"

    bids {
        varchar(100) id PK "e.g. GEM_2025_B_6726924"
        varchar(100) bid_no UK "Official Bid Number"
        varchar(100) ra_no "Associated RA Number"
        varchar(100) bid_type "Product Bid/RAs, Service, BOQ"
        varchar(50) product_type "Product / Service"
        varchar(50) status "active, closed, cancelled"
        timestamptz start_datetime "Publication Timestamp"
        timestamptz end_datetime "Bid Submission Deadline"
        timestamptz bid_opening_datetime "Technical Opening"
        int bid_offer_validity_days "Validity Period"
        numeric estimated_value "Estimated Tender Budget (INR)"
        numeric emd_amount "Earnest Money Deposit (INR)"
        boolean emd_required "EMD Flag"
        varchar(100) emd_advisory_bank "Bank Guarantee Provider"
        numeric epbg_percent "Performance Security %"
        boolean mse_preference "MSE Purchase Preference"
        boolean startup_relaxation "Startup Waiver Flag"
        text_array required_documents "Mandatory Seller Certificates"
        jsonb raw_data "Full Scraped Unaltered Backup"
    }

    bid_items {
        bigserial id PK
        varchar(100) bid_id FK "References bids.id"
        int item_index "Item Order Index"
        varchar(500) item_category "Product Category Name (GIN Trigram)"
        numeric quantity "Total Units Required"
        varchar(50) unit "Unit of Measure"
        jsonb specifications "Full Technical Key-Value Specs"
    }

    bid_consignees {
        bigserial id PK
        varchar(100) bid_id FK "References bids.id"
        varchar(255) officer_name "Consignee Officer Name"
        text address "Warehouse / Delivery Destination"
        varchar(100) city "Delivery City"
        varchar(10) pincode "6-Digit Postal Code (Indexed)"
        numeric quantity "Allocated Delivery Quantity"
        int delivery_days "Lead Time in Days"
    }

    bid_atc_checklist_items {
        bigserial id PK
        varchar(100) bid_id FK "References bids.id"
        varchar(100) category "One of 8 Legal Domains"
        text clause_text "Extracted Compliance Requirement"
        int clause_order "Ordering Index"
    }

    bid_atc_physical_submissions {
        bigserial id PK
        varchar(100) bid_id FK "References bids.id"
        varchar(255) item_name "Demand Draft, Sample, Guarantee"
        varchar(255) deadline "Submission Deadline Window"
        varchar(255) in_favor_of "Payee Organization Name"
        varchar(255) payable_at "Payee City / Branch"
        text delivery_address "Physical Dispatch Office"
    }

    gem_bid_chunks {
        bigserial id PK
        varchar(100) bid_id FK "References bids.id"
        varchar(50) chunk_type "item | compliance | general_pdf"
        text chunk_text "Normalized Passage Content"
        jsonb metadata "Contextual Filter Attributes"
        vector_768 embedding "768-dim BGE Embeddings (HNSW Cosine)"
    }
```

---

## 🧩 4. Data Partitioning & Frontend Sub-Resource Flow

Tender data is deconstructed into **10 modular partitions**, allowing frontend tabs (React / Vue) to load in **<10ms** without downloading massive multi-megabyte payloads:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 MASTER TENDER DOSSIER                                  │
│                               GET /api/v1/bids/{bid_id}                                │
├──────────────┬──────────────────┬─────────────────┬────────────────┬───────────────────┤
│ [P1: Header] │ [P2: Buyer Org]  │ [P3: Items]     │ [P4: Logistics]│ [P5: Financials]  │
│   /header    │     /buyer       │     /items      │  /consignees   │   /financials     │
├──────────────┼──────────────────┼─────────────────┼────────────────┼───────────────────┤
│ [P6: Policy] │ [P7: Documents]  │ [P8: ATC AI]    │ [P9: Submits]  │ [P10: Schedules]  │
│   /policy    │    /documents    │      /atc       │  /submissions  │    /schedules     │
└──────────────┴──────────────────┴─────────────────┴────────────────┴───────────────────┘
```

| Partition | Sub-Route | DB Source | Frontend Component | B2B Commercial Feed |
|---|---|---|---|---|
| **P1: Lifecycle & Identity** | `/header` | `bids` scalars | Tender Header Card, Countdown Timer | Live Opportunity Feeds |
| **P2: Buyer & Governance** | `/buyer` | `bids` scalars | Buyer Info Sidebar, Department Hierarchy | Government Vendor Intelligence |
| **P3: Items & Specs** | `/items` | `bid_items` | Technical Specs Tab, OEM Quoting Engine | Product Supplier Catalog Feed |
| **P4: Logistics & Consignees** | `/consignees` | `bid_consignees` | Consignee Map & Multi-Location Table | Freight Logistics & 3PL Quotes |
| **P5: Financials & Bonds** | `/financials` | `bids` scalars | Financial Sizing Card, EMD Advisory | Fintech Lending & Bank Guarantees |
| **P6: Policy & Relaxations** | `/policy` | `bids` scalars | MSME & Startup Qualification Modal | Small Business Tender Matching |
| **P7: Mandatory Documents** | `/documents` | `bids` array | Pre-Bid Document Readiness Checklist | Bidding Readiness Auditor |
| **P8: ATC Compliance Clauses** | `/atc` | `bid_atc_checklist_items`| 8-Domain Compliance Risk Matrix | Legal & Compliance Risk Reports |
| **P9: Physical Submissions** | `/submissions` | `bid_atc_physical_submissions`| Offline Hardcopy Tracker, DD Deadlines | Courier & Sample Delivery Alerts |
| **P10: Evaluation Schedules** | `/schedules` | `bid_evaluation_schedules`| Multi-Lot Split-Bidding Grid | Segmented Consortia Quoting |

---

## 🛡️ 5. Production Dokploy & Hostinger KVM 4 VPS Topology

The production environment is orchestrated via **Dokploy PaaS** and **Traefik**, enforcing strict CPU and RAM ceilings to guarantee 100% server stability on Hostinger KVM 4 VPS (srv1701681):

```mermaid
graph TB
    subgraph INTERNET ["External Traffic"]
        USER["User HTTPS Requests"]
        WEBHOOK["External Webhooks & B2B Feeds"]
    end

    subgraph DOKPLOY_HOST ["Hostinger KVM 4 VPS (Ubuntu 24.04 LTS — 16 GB RAM / 4 vCPUs)"]
        TRAEFIK["Traefik v3 Reverse Proxy & Automated SSL (Let's Encrypt)"]

        subgraph SYSTEM_DOCKER ["GeMBridge Isolated Docker Network (gem_engine_network)"]
            GATEWAY["gem-fastapi-gateway\n(Port 8000 | 0.4 CPU / 350M RAM)"]
            REDIS["gem-engine-redis\n(Port 6379 | 0.3 CPU / 512M RAM)"]
            BEAT["gem-celery-beat\n(Clock Daemon | 0.1 CPU / 150M RAM)"]
            W_SCRAPER["gem-worker-scraper\n(Playwright | 1.0 CPU / 1200M RAM | 2GB shm)"]
            W_DOC["gem-worker-document\n(PyMuPDF & Mistral | 0.5 CPU / 600M RAM)"]
            W_ATC["gem-worker-atc\n(Gemini & BGE Embeddings | 0.5 CPU / 1200M RAM)"]
            FLOWER["gem-flower-telemetry\n(Port 5555 | 0.1 CPU / 150M RAM)"]
        end

        subgraph SHARED_SERVICES ["Host VPS Shared Persistent Services"]
            PG_HOST[("Shared PostgreSQL 18\n(localhost:5432 / gem-bridge)\nextra_hosts: host.docker.internal")]
            MINIO_HOST["Shared MinIO S3\n(localhost:9000 / gem-tenders)"]
            HF_CACHE["Persistent HuggingFace Cache Volume\n(gem_hf_cache -> /root/.cache/huggingface)"]
        end
    end

    USER & WEBHOOK -->|HTTPS :443| TRAEFIK
    TRAEFIK -->|Reverse Proxy :8000| GATEWAY
    TRAEFIK -->|Basic Auth :5555| FLOWER

    GATEWAY --> REDIS & PG_HOST & MINIO_HOST
    BEAT --> REDIS
    W_SCRAPER & W_DOC & W_ATC --> REDIS
    W_SCRAPER --> MINIO_HOST
    W_DOC --> MINIO_HOST & PG_HOST
    W_ATC --> PG_HOST & HF_CACHE & MINIO_HOST
```

---

*Maintained by GeMBridge Engineering Architecture Team.*
