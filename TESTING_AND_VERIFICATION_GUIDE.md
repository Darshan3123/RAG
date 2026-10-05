# 🧪 GeM Pipeline — Master Command Reference & Testing Guide

This guide provides an exhaustive reference of **all available CLI commands** for the GeM Tender Intelligence System, covering:
* **🧹 Database & Storage Cleaning Commands** (Reset DB, ChromaDB, downloads, logs, purge all)
* **📊 Database & Storage Inspection Commands** (Stats, SQLite queries, JSON exports)
* **⚡ Automated Verification Test Suites** (All-in-one test runners)
* **⚙️ Web Scraping & Document Processing** (Single bid, full pass, daemon loop)
* **📋 ATC Compliance Analysis** (Single tender, batch directory)
* **🔍 Hybrid RAG & Question Answering** (Q&A, filtered search, interactive chat, re-indexing)
* **🌐 Pluggable OCR Configuration & Costing** (Mistral, Gemini, OpenAI, Mineru)

---

## 🚀 Environment Setup

Open PowerShell or Command Prompt, navigate to the `Scrapper & RAG Pipeline` directory, and activate the virtual environment:

```powershell
cd "c:\Projects\GeM\Scrapper & RAG Pipeline"
.\venv\Scripts\activate
```

---

## 🧹 1. Database & Storage Cleaning Commands

Use these commands whenever you need to clear old data, reset tests, or perform a clean reinstall.

### A. Python CLI Cleaning Flags (Recommended)

| Command | Action Performed | What Gets Deleted |
| :--- | :--- | :--- |
| `python main.py --clear-db` | Clears SQLite database & JSON export only | `storage/gem_bids.db`, `storage/gem_bids.json` |
| `python main.py --clear-chroma` | Clears ChromaDB vector embeddings only | `storage/chroma_db/` directory |
| `python main.py --clear-downloads` | Clears all downloaded PDFs and bid folders | `downloads/*` (preserves folder structure) |
| `python main.py --clear-logs` | Clears all execution log files | `logs/*` |
| `python main.py --reset` | **Standard Reset:** Clears SQLite DB, JSON, ChromaDB, and temp markdown | `storage/gem_bids.db`, `storage/gem_bids.json`, `storage/chroma_db/`, `output_md/` |
| `python main.py --reset-all`<br/>*(or `python main.py --purge`)* | **Complete Factory Reset:** Purges everything (DB, ChromaDB, downloads, logs) | `storage/`, `downloads/`, `logs/`, `output_md/` |

#### Examples:
```powershell
# Reset only vector database (useful before running --reindex)
python main.py --clear-chroma

# Reset only SQLite database and JSON export
python main.py --clear-db

# Clean slate for fresh testing (DB + ChromaDB)
python main.py --reset

# Complete wipe of all scraped files, logs, and databases
python main.py --reset-all
```

---

### B. PowerShell One-Liner Purge Commands (Direct File Deletion)

If you prefer direct PowerShell terminal commands:

```powershell
# Delete only SQLite database file:
Remove-Item -Path "storage\gem_bids.db" -Force -ErrorAction SilentlyContinue

# Delete only ChromaDB folder:
Remove-Item -Path "storage\chroma_db" -Recurse -Force -ErrorAction SilentlyContinue

# Delete only JSON export file:
Remove-Item -Path "storage\gem_bids.json" -Force -ErrorAction SilentlyContinue

# Delete all downloaded bid PDFs & subfolders:
Remove-Item -Path "downloads\*" -Recurse -Force -ErrorAction SilentlyContinue

# Delete all log files:
Remove-Item -Path "logs\*" -Recurse -Force -ErrorAction SilentlyContinue

# Purge all Python __pycache__ folders:
Get-ChildItem -Path . -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force
```

---

## 📊 2. Database & Storage Inspection Commands

Check record counts, database integrity, and storage paths.

### A. Fast CLI Summary
```powershell
python main.py --stats
```
**Output Example:**
```text
==========================================
  GeM Bid Scraper — System Stats
==========================================
  SQLite total bids  : 15
  New (unseen)       : 3
  Total runs logged  : 2
  Vector store chunks: 116
  ChromaDB path      : storage\chroma_db
==========================================
```

### B. Direct SQLite Terminal Inspection (Python One-Liners)
Query the SQLite database directly without installing external tools:

```powershell
# 1. Count total bids in SQLite:
python -c "import sqlite3; conn = sqlite3.connect('storage/gem_bids.db'); print('Total bids in DB:', conn.execute('SELECT COUNT(*) FROM bids').fetchone()[0])"

# 2. View recent bid numbers, departments, and estimated values:
python -c "import sqlite3; conn = sqlite3.connect('storage/gem_bids.db'); [print(f'{r[0]} | {r[1]} | ₹{r[2]}') for r in conn.execute('SELECT bid_no, department, estimated_value FROM bids ORDER BY id DESC LIMIT 5').fetchall()]"

# 3. Check schema columns of the bids table (verifying atc_analysis column):
python -c "import sqlite3; conn = sqlite3.connect('storage/gem_bids.db'); print([c[1] for c in conn.execute('PRAGMA table_info(bids)').fetchall()])"

# 4. Trigger manual JSON export from SQLite:
python -c "from storage.database import BidDatabase; BidDatabase().export_json()"
```

### C. ChromaDB Vector Store Inspection
```powershell
# Check vector store collection statistics and chunk count:
python -c "from rag.vector_store import stats; print(stats())"
```

---

## ⚡ 3. Automated Verification Test Suites

Run these to verify that every component (Normalizer, Parser, ATC Extractor, SQLite, ChromaDB, Hybrid RAG, Pluggable OCR) is functioning with zero errors.

### A. Master Repository Verification Suite (Phases 1 – 3)
```powershell
python test_all_phases.py
```
* **Phase 1 (Data Normalizer):** Validates INR currency parsing (`₹18.85 Lakhs`, `₹1.5 Crore`, `₹50,000/-` $\rightarrow$ float numbers), ISO 8601 timestamps, and schema validation.
* **Phase 1 (Core Parser):** Tests real Markdown extraction for financial values (`estimated_value`), EMD totals, and schedule structures.
* **Phase 2 (ATC Compliance Extraction):** Tests structured 5-section checklist extraction and live Gemini API calls.
* **Phase 2 (SQLite Auto-Migration):** Verifies table schemas and `atc_analysis` column auto-migration.
* **Phase 3 (ChromaDB Vector Store):** Verifies collection health and indexed chunks.
* **Phase 3 (Hybrid RAG Search & Q&A):** Tests catalog search and clause-level question answering with automatic fallback to Gemini.

---

### B. Pluggable OCR & Provider Test Suite
```powershell
python test_ocr_providers.py
```
* **Factory Resolution:** Validates dynamic loading of `mistral`, `gemini`, `openai`, and `mineru` providers.
* **Pricing Catalog:** Validates exact USD and INR billing calculations across all supported models.
* **Mistral HTML Table Substitution:** Verifies that `[tbl-X.html]` references are replaced with native `<table>...</table>` markup.
* **Parser Compatibility:** Ensures Mistral-generated Markdown with embedded HTML tables is cleanly parsed by `core/parser.py`.
* **In-Memory Cache & Concurrency Lock:** Verifies SHA-256 deduplication and atomic concurrency locking without Django.

---

## ⚙️ 4. Web Scraping & Document Processing Commands

Automate GeM portal interaction, PDF downloading, OCR conversion, and data persistence.

### A. Scrape a Specific Single Bid
Downloads the PDF, converts it to Markdown via the active OCR engine, extracts hyperlinks, runs parser/normalizer/ATC, and indexes into SQLite & ChromaDB:
```powershell
python main.py --bid "GEM/2026/B/7768206"
```

### B. Run a Single Full Scrape Pass
Scrapes up to `TARGET_PER_TYPE` bids across active tender categories and then terminates:
```powershell
python main.py --once
```

### C. Launch Continuous Scheduled Hourly Scraper (Daemon)
Runs an automated scraping loop every `SCRAPE_INTERVAL_MINUTES` (configured in `.env`):
```powershell
python main.py
```
*(Press `Ctrl + C` to shut down gracefully).*

---

## 📋 5. ATC Compliance Analysis Commands

Extract the 5-section procurement compliance checklist (Standard Docs, Clarified ATC Uploads, Exemptions, Physical Submissions, Commercial Terms) using Gemini or local Qwen:

### A. Analyze a Specific Tender Markdown
```powershell
# Medical analyzer bid with extensive commercial and technical clauses:
python main.py --analyze-atc "ATC EXTRACTOR/TEST_MARKDOWNS/GEM_2025_B_6904960"

# Defense equipment tender:
python main.py --analyze-atc "ATC EXTRACTOR/TEST_MARKDOWNS/GEM_2026_B_7495766"
```
> **Output:** Writes `<bid_no>_ATC.md` directly into the tender directory and displays counts for all 5 compliance categories.

### B. Batch Analyze All Downloaded Tenders
```powershell
python main.py --analyze-atc "downloads"
```

---

## 🔍 6. Hybrid RAG & Question Answering Commands

Query the tender database using hybrid retrieval (**BAAI/bge-base-en-v1.5 Dense Embeddings + BM25 Sparse Search + BAAI/bge-reranker-base Cross-Encoder**):

### A. Clause-Level Compliance Question Answering
```powershell
python main.py --ask "What are the exemption rules and documents required for MSEs in the medical analyzer bid?"
```

```powershell
python main.py --ask "What is the warranty period and SLA penalty for the medical analyzer tender?"
```

```powershell
python main.py --ask "What are the EMD requirements and advisory bank details?"
```

### B. Catalog Search & Tender Filtering
```powershell
# Broad search across all tenders:
python main.py --ask "What bids are there for desktop computers?"

# Filtered search by Product Type:
python main.py --ask "desktop computer" --filter product_type=Product
```

### C. Interactive Terminal RAG Chat Session
Chat continuously with your tender catalog:
```powershell
python main.py --chat
```
**In-Chat Commands:**
* `<question>` — Performs hybrid search and generates an answer with source attribution.
* `f:<key>=<value> <question>` — Applies metadata filters (e.g. `f:product_type=Product computer`).
* `/search <question>` — Vector retrieval only (returns matching chunks without calling LLM).
* `quit` / `exit` / `bye` — Closes the chat session.

### D. Re-index All Bids into Vector Store (Self-Healing)
Clears and re-indexes all tenders from SQLite into ChromaDB with fresh chunking and embeddings:
```powershell
python main.py --reindex
```

---

## 🌐 7. Pluggable OCR Configuration & Costing

The OCR engine can be swapped seamlessly by setting `OCR_PROVIDER` in `Scrapper & RAG Pipeline/.env`:

```bash
# ---------------------------------------------------------
# OCR / DOCUMENT INTELLIGENCE CONFIG
# Options: mistral | gemini | openai | mineru
# ---------------------------------------------------------
OCR_PROVIDER=mistral

# Mistral Configuration (Default)
MISTRAL_API_KEY=your_mistral_api_key_here
MISTRAL_OCR_MODEL=mistral-ocr-3-0

# Gemini Configuration (uses GEMINI_API_KEY)
GEMINI_OCR_MODEL=gemini-2.5-flash

# OpenAI Configuration
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_OCR_MODEL=gpt-4o-mini

# Currency Conversion
USD_TO_INR_RATE=86.50
```

### Provider Feature & Cost Summary:

| Provider | Setting | Pricing Basis | Est. Cost (10-Page GeM Bid) | GPU Needed? |
| :--- | :--- | :--- | :--- | :--- |
| **Mistral OCR** *(Recommended)* | `OCR_PROVIDER=mistral` | **\$1.00 / 1,000 pages** | **~\$0.010** (~₹0.86) | ❌ None (Cloud API) |
| **Google Gemini** | `OCR_PROVIDER=gemini` | **\$0.075 / 1M in**, **\$0.30 / 1M out** | **~\$0.001 – \$0.003** (~₹0.15) | ❌ None (Cloud API) |
| **Google Gemini Lite** | `gemini-3.1-flash-lite` | **\$0.0375 / 1M in**, **\$0.15 / 1M out**| **~\$0.0008** (~₹0.07) | ❌ None (Cloud API) |
| **OpenAI ChatGPT** | `OCR_PROVIDER=openai` | **\$0.15 / 1M in**, **\$0.60 / 1M out** | **~\$0.003 – \$0.006** (~₹0.40) | ❌ None (Cloud API) |
| **Mineru VLM** | `OCR_PROVIDER=mineru` | **\$0.00 API cost** | **\$0.00** | ✅ GPU with 4GB+ VRAM |

### Telemetry Saved in Every Bid JSON Artifact:
Located in `downloads/<bid_no>/<bid_no>.json`:
```json
"telemetry": {
    "ocr": {
        "provider": "mistral",
        "model": "mistral-ocr-3-0",
        "pages_processed": 10,
        "input_tokens": 0,
        "output_tokens": 2840,
        "latency_seconds": 3.42,
        "estimated_cost_usd": 0.01,
        "estimated_cost_inr": 0.865,
        "details": {
            "price_model_used": "mistral-ocr-3-0",
            "usd_to_inr_rate": 86.5
        }
    }
}
```

---

## 📋 Quick Command Cheat Sheet

```powershell
# 1. SYSTEM STATS & STATUS
python main.py --stats

# 2. RUN FULL AUTOMATED TESTS
python test_all_phases.py
python test_ocr_providers.py

# 3. SCRAPE A SPECIFIC BID
python main.py --bid "GEM/2026/B/7768206"

# 4. ASK A RAG COMPLIANCE QUESTION
python main.py --ask "What are the exemption rules for MSEs?"

# 5. LAUNCH INTERACTIVE RAG CHAT
python main.py --chat

# 6. EXTRACT ATC COMPLIANCE CHECKLIST
python main.py --analyze-atc "ATC EXTRACTOR/TEST_MARKDOWNS/GEM_2025_B_6904960"

# 7. RE-INDEX CHROMA VECTOR STORE
python main.py --reindex

# 8. RESET STORAGE & DATABASES
python main.py --clear-db          # Clears SQLite & JSON only
python main.py --clear-chroma      # Clears ChromaDB only
python main.py --clear-downloads   # Clears downloads only
python main.py --clear-logs        # Clears logs only
python main.py --reset             # Resets DB + ChromaDB
python main.py --reset-all         # Complete wipe (DB, ChromaDB, downloads, logs)
```
