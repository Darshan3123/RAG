# 🏛️ GeM Bid Scraper & RAG System — Project Overview

> **Last Updated:** September 2026  
> **Project Path:** `f:\Projects\gem_scraper`  
> **Python Version:** 3.12 (see [`.python-version`](.python-version))

---

## 📌 What Is This Project?

This is an **automated end-to-end pipeline** for scraping, parsing, storing, and semantically querying Indian Government e-Marketplace (**GeM**) bid/tender data from `bidplus.gem.gov.in`.

The system has two major responsibilities:

| Layer | Purpose |
|-------|---------|
| **Scraping Pipeline** | Automatically browses GeM, downloads bid PDFs, converts them to Markdown via an AI Vision-Language Model (Mineru VLM), parses structured fields, and stores everything locally |
| **RAG (Retrieval-Augmented Generation)** | Embeds the parsed bid text into a local vector database (ChromaDB), and lets you ask natural-language questions against all scraped bids — answered by a local/remote LLM |

**In short:** You run the scraper → it collects live GeM tenders → you query `"show me all pump bids under Railways"` → the system retrieves and answers using your local data, with zero dependence on any external API.

---

## 🏗️ Architecture Overview

```
bidplus.gem.gov.in
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│                    SCRAPING PIPELINE                         │
│                                                              │
│  GemBrowser (Playwright stealth) ──► Card HTML parsing       │
│       │                               (core/parser.py)       │
│       ▼                                                      │
│  PDF Download ──► PyMuPDF hyperlink extraction               │
│       │                                                      │
│       ▼                                                      │
│  Mineru VLM (vLLM server) ──► Markdown conversion            │
│       │                                                      │
│       ▼                                                      │
│  Structured JSON + .html + .pdf + .md ──► downloads/{bid}/   │
│       │                                                      │
│       ▼                                                      │
│  SQLite DB (storage/gem_bids.db)                             │
└───────────────────────┬──────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────┐
│                       RAG LAYER                              │
│                                                              │
│  Embedder (BGE-base-en-v1.5) ──► ChromaDB Vector Store       │
│                                                              │
│  Query Engine:                                               │
│    ① Dense Retrieval (cosine)                               │
│    ② BM25 Sparse Retrieval                                  │
│    ③ RRF Fusion                                             │
│    ④ Cross-Encoder Reranker (bge-reranker-base)             │
│    ⑤ LLM Answer (Ollama / OpenAI / retrieval-only)          │
└──────────────────────────────────────────────────────────────┘
```

---

## 📂 Project Structure

```
gem_scraper/
├── main.py                        ← CLI entry point (all modes)
├── requirements.txt               ← All Python dependencies
├── .env.example                   ← Environment variable template
│
├── config/
│   └── settings.py                ← All config loaded from .env
│
├── core/
│   ├── browser.py                 ← Playwright stealth browser (GemBrowser)
│   └── parser.py                  ← HTML card parser + PDF markdown parser
│
├── pipeline/
│   ├── scraper.py                 ← Main scrape orchestration + Mineru VLM
│   └── scheduler.py               ← Hourly loop + new-bid alert
│
├── rag/
│   ├── embedder.py                ← Text chunking + BGE sentence embeddings
│   ├── vector_store.py            ← ChromaDB upsert + hybrid search + reranker
│   ├── query_engine.py            ← QueryEngine class (ask / search_only)
│   └── llm.py                     ← LLM prompt builder + Ollama/OpenAI callers
│
├── storage/
│   ├── database.py                ← SQLite ORM (BidDatabase: upsert, dedup, stats)
│   ├── gem_bids.db                ← SQLite database (live data)
│   └── chroma_db/                 ← ChromaDB persistent vector store
│
├── utils/
│   ├── antibot.py                 ← Human-like delays, random UA/viewport rotation
│   ├── logger.py                  ← Rotating file logger per module
│   └── pdf_hyperlinks.py          ← PyMuPDF hyperlink extraction + MD injection
│
├── downloads/                     ← Per-bid artifact folders
│   └── GEM_2026_B_XXXXXXX/
│       ├── *.html                 ← Card HTML snapshot
│       ├── *.pdf                  ← Original bid PDF
│       ├── *.md                   ← Mineru VLM Markdown conversion
│       └── *.json                 ← Full structured JSON schema
│
├── logs/                          ← Per-module rotating log files
│   ├── main.log, scraper.log, browser.log, parser.log
│   ├── embedder.log, vector_store.log, query_engine.log
│   └── scheduler.log, database.log, llm.log
│
└── STANDLONE TEST SCRIPTS/        ← Development / debug test scripts
    ├── TEST_STANDALONE_SCRAPPER.py
    ├── TEST_STANDALONE_SCRAPPER_MULTI_ITEM_ONLY.py
    ├── TEST_STANDALONE_SCRAPPER_SCRAPE_PARTICULAR_BID.py
    ├── TEST_STANDALONE_SCRAPPER_WITH_EVAL_METHODS_SPLIT_REPORT.py
    └── TEST_STANDALONE_SCRAPPER_WITH_EVAL_METHODS_SPLIT_REPORT_WITH_EXTERNAL_BID_ATC.py
```

---

## ✅ What Has Been Done

### 1. Scraping Infrastructure
- [x] **Playwright stealth browser** (`core/browser.py`) — headless Chromium with anti-bot UA rotation, random viewports, randomised delays, and `--disable-blink-features=AutomationControlled`
- [x] **All 9 GeM bid category types** scraped: Product Bid/RAs, Service Bid/RAs, Bid To RAs, Product Custom Bid/RAs, BOQ Bids, Rate Contract Bids, Global Tender, Limited Tender, Single Tender
- [x] **Pagination support** — iterates pages with an `empty_pages` counter to stop gracefully
- [x] **Card HTML parsing** (`core/parser.py`) — extracts item name, quantities, departments, dates, product type from DOM
- [x] **PDF download** for both main Bid PDF and optional Reverse Auction (RA) PDF
- [x] **Targeted single-bid scrape mode** (`--bid`) — uses GeM's advanced search to pull one specific bid number

### 2. Document Processing
- [x] **Mineru VLM integration** (via `Mineru_Document_To_Markdown`) — GPU-accelerated vision-language model converts scanned/complex PDFs to Markdown with formula and table support
- [x] **Zero-save mode** — Mineru returns Markdown in-memory; no temp output directory needed
- [x] **vLLM server lifecycle** — server started before scrape run, shut down cleanly after; tuned for RTX 2050 (4 GB VRAM): `max_gpu_util=0.78`, `model_len=4096`, `batch_size=16`
- [x] **Hyperlink extraction** (`utils/pdf_hyperlinks.py`) — PyMuPDF extracts all embedded URIs from Bid PDF and RA PDF; injected as a dedicated section in Markdown for RAG enrichment
- [x] **Structured field parsing** from Markdown — Ministry/State, Department, Organisation, Office, financials, bid type, process kind, base type
- [x] **4 output artifacts per bid** saved to `downloads/{bid_no}/`: `.html`, `.pdf`, `.md`, `.json`

### 3. Storage Layer
- [x] **SQLite database** (`storage/database.py`) — `bids` table with deduplication on `document_url`, `is_new` flag for new-bid detection, `run_log` table for run history
- [x] **JSON export** after each scrape run (PDF text stripped for file size)
- [x] **Upsert logic** — new bids inserted; existing bids only update `last_seen`, `ra_no`, `corrigendum_url`

### 4. RAG (Retrieval-Augmented Generation) Layer
- [x] **BGE-base-en-v1.5 embeddings** (local, offline, CUDA-accelerated) with automatic BGE query instruction prefix
- [x] **Metadata-card chunking** — chunk[0] is always a high-signal structured card; subsequent chunks are sliding windows over full PDF text
- [x] **ChromaDB vector store** (persistent, cosine space, HNSW index)
- [x] **Hybrid retrieval**: Dense (cosine) + BM25 sparse retrieval fused via **Reciprocal Rank Fusion (RRF)**
- [x] **Cross-encoder reranker** (`BAAI/bge-reranker-base`) with sigmoid logit normalisation — biggest quality booster
- [x] **Result deduplication** — one result per unique `bid_no` (best chunk wins)
- [x] **Score filtering** — results below 70% of top result score dropped; BM25 false positives filtered by semantic signal check
- [x] **Metadata filter support** — query with `product_type=Product` or any field
- [x] **Smart top-k** — auto-scales `k` up for listing intent queries, down for focused lookup queries

### 5. LLM Answer Layer
- [x] **Three LLM modes**: `ollama` (local, default), `openai`, or retrieval-only (no LLM)
- [x] **Zero-hallucination system prompt** — LLM strictly limited to retrieved bid context only; N/A for missing fields
- [x] **Prompt builder** with up to 8 bids formatted in a structured block per bid
- [x] **Graceful fallback** — if Ollama/OpenAI call fails, falls back to a plain formatted text dump

### 6. CLI Interface (`main.py`)
- [x] `python main.py` — continuous hourly scrape loop (default)
- [x] `python main.py --once` — single scrape run and exit
- [x] `python main.py --bid "GEM/2026/B/..."` — scrape one specific bid
- [x] `python main.py --ask "query"` — single RAG Q&A query
- [x] `python main.py --ask "q" --filter product_type=Product` — filtered RAG query
- [x] `python main.py --chat` — interactive terminal RAG chat session with `/search` mode
- [x] `python main.py --stats` — SQLite + ChromaDB statistics
- [x] `python main.py --reindex` — re-index all DB records into ChromaDB
- [x] `python main.py --reset` — wipe DB + vector store for clean testing

### 7. Scheduler & Alerting
- [x] Configurable interval (default 60 min) via `SCRAPE_INTERVAL_MINUTES`
- [x] `SIGINT` / `SIGTERM` handlers — graceful shutdown between runs
- [x] New-bid detection after every run — logs a formatted alert summary
- [x] Extension hook in scheduler for email/Slack notifications (stub left in code)

### 8. Anti-Bot / Stealth
- [x] Random user-agent pool (5 agents: Chrome Windows, Edge, Chrome Mac, Firefox, Chrome Linux)
- [x] Random viewport pool (1920×1080, 1440×900, 1366×768, 1536×864)
- [x] Randomised delays between pages, cards, filter clicks, PDF downloads
- [x] `en-IN` locale + `Asia/Kolkata` timezone in browser context
- [x] Multiprocessing-based CLI spinner (avoids GIL lock during GPU ops)

### 9. Test & Debug Scripts
- [x] 5 standalone test scripts in `STANDLONE TEST SCRIPTS/` covering: full scrape, multi-item, targeted bid, eval methods with split reporting, and external bid ATC evaluation

---

## ❌ What Needs To Be Done (Pending)

### 🔴 High Priority

| # | Task | Notes |
|---|------|-------|
| 1 | **Email / Slack notification integration** | Extension hook stub exists in [`pipeline/scheduler.py`](pipeline/scheduler.py#L76-L80). Needs actual `send_email_alert(new_bids)` or `push_to_slack_webhook(new_bids)` implementation |
| 2 | **Web / Dashboard UI** | Currently CLI-only. No web interface for browsing scraped bids or asking questions. A FastAPI (`fastapi` is already in `requirements.txt`) + simple frontend (React/HTMX) needs to be built |
| 3 | **Error retry with backoff** | `MAX_RETRIES_PER_BID` and `RETRY_DELAY_SECONDS` config keys exist but retry logic is **not implemented** in the scraper — failed cards are counted as errors and skipped |
| 4 | **RA / Corrigendum detection pipeline** | RA PDFs are downloaded but their content is not separately parsed or indexed as distinct documents in the RAG layer |

### 🟡 Medium Priority

| # | Task | Notes |
|---|------|-------|
| 5 | **Multi-item bid support** | Some bids have multiple line items. The current `card_data["card"]["items"][0]` only captures the first item for DB record. Standalone test `TEST_STANDALONE_SCRAPPER_MULTI_ITEM_ONLY.py` exists but not integrated into the main pipeline |
| 6 | **Normalization layer** | The JSON schema has a `"normalized": {}` field that is always empty. Financial value normalization (lakhs/crores → numeric), date standardisation (DD-MM-YYYY → ISO), etc. should be populated |
| 7 | **Validation layer** | The JSON schema has `"validation": {"issues": []}` always empty. Field-level validation (missing bid_no, invalid dates, zero estimated value) should flag issues |
| 8 | **ChromaDB re-index is manual** | Currently you must run `--reindex` manually after a `--reset`. Auto-trigger re-index when the DB has records but ChromaDB is empty would improve reliability |
| 9 | **RAG context window — beyond 8 bids** | `MAX_BIDS_IN_PROMPT = 8` in `rag/llm.py`. For listing queries with many results, the LLM only sees 8. Pagination or summarisation for large result sets is not implemented |

### 🟢 Low Priority / Nice-to-Have

| # | Task | Notes |
|---|------|-------|
| 10 | **Windows-native setup** | `setup_env.sh` and `sync_to_github.sh` are Linux shell scripts. No PowerShell equivalents exist; setup on Windows requires manual steps |
| 11 | **Bid status tracking** | Bids that expire (past `end_date`) are not automatically marked as closed in the DB — no TTL or status update mechanism |
| 12 | **Corrigendum download & parsing** | `corrigendum_url` is stored but the PDF is never downloaded or parsed |
| 13 | **Duplicate chunk cleanup** | After `--reindex`, old chunks for the same bid_no are deleted before re-inserting. But if a bid's PDF text changes (corrigendum), old stale content may persist until next `--reindex` |
| 14 | **Docker / containerisation** | No `Dockerfile` or `docker-compose.yml` exists. Containerising would simplify deployment especially given the GPU + vLLM dependency |
| 15 | **Unit/integration tests** | Only standalone manual test scripts exist. No `pytest` test suite with assertions |

---

## ⚙️ Environment Configuration (`.env`)

Copy `.env.example` to `.env` and set:

```bash
# Key settings to configure
SCRAPE_INTERVAL_MINUTES=60        # How often to scrape
TARGET_PER_TYPE=10                 # Bids to collect per category per run

RAG_LLM_PROVIDER=ollama            # ollama | openai | (empty = retrieval only)
OLLAMA_MODEL=llama3                # Local model name
OPENAI_API_KEY=                    # Only if using OpenAI

HF_TOKEN=your_token_here           # Required for HuggingFace model downloads
```

---

## 🚀 Quick Start

```bash
# 1. Install dependencies (Linux/WSL with CUDA 13.0)
uv venv -p 3.12 --seed ~/VLLM_Env
source ~/VLLM_Env/bin/activate
uv pip install -r requirements.txt --torch-backend=cu130 --index-strategy unsafe-best-match --no-build-isolation

# 2. Install Playwright browser
playwright install chromium

# 3. Copy and configure .env
cp .env.example .env
# Edit .env with your settings

# 4. Run a single scrape
python main.py --once

# 5. Ask a question
python main.py --ask "show me all bids for water pumps"

# 6. Start interactive chat
python main.py --chat
```

---

## 🔑 Key Technologies

| Technology | Role |
|------------|------|
| **Playwright** | Stealth headless browser automation |
| **Mineru VLM** (`vLLM`) | GPU-accelerated PDF → Markdown (vision-language model) |
| **PyMuPDF** | Hyperlink extraction from PDFs |
| **SQLite** | Structured bid storage + deduplication |
| **ChromaDB** | Persistent vector store (HNSW cosine) |
| **BAAI/bge-base-en-v1.5** | Dense sentence embeddings (local, offline) |
| **BM25Okapi** (`rank-bm25`) | Sparse keyword retrieval |
| **BAAI/bge-reranker-base** | Cross-encoder reranking |
| **Ollama / OpenAI** | Final LLM answer generation |
| **FastAPI** | (Installed, not yet used — reserved for future Web UI) |

---

## 📊 Data Flow — Single Bid Lifecycle

```
GeM Portal Card (HTML)
    ↓
[GemBrowser] extracts card metadata + doc URL
    ↓
[PDF Download] → downloads/{bid_no}/{bid_no}.pdf
    ↓
[PyMuPDF] → hyperlinks extracted
    ↓
[Mineru vLLM] → PDF → Markdown (in-memory)
    ↓
[inject_hyperlinks_into_markdown] → enriched Markdown
    ↓
[core/parser.py] → structured fields (departments, financials, bid type)
    ↓
Saved: .html + .pdf + .md + .json → downloads/{bid_no}/
    ↓
[BidDatabase.upsert()] → SQLite gem_bids.db
    ↓ (if new bid)
[vector_store.upsert_bid()] → metadata card + PDF chunks → ChromaDB
```

---

*Generated by Antigravity code analysis — September 2026*
