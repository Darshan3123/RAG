# 📖 GeM Pipeline — Commands Guide

A comprehensive, task-oriented command reference for the **GeM Tender Scraper, Pluggable OCR Engine, ATC Compliance Analyzer, and Hybrid RAG System**.

---

## 🚀 Environment Setup

Before running any command, navigate to the `Scrapper & RAG Pipeline` directory and activate the virtual environment:

```powershell
cd "c:\Projects\GeM\Scrapper & RAG Pipeline"
.\venv\Scripts\activate
```

> **Note:** If Playwright browsers were not yet downloaded on your system, install Chromium once:
> ```powershell
> playwright install chromium
> ```

---

## ⚡ 1. Full Pipeline Commands (End-to-End)

Run these commands to execute the complete end-to-end pipeline: **Download PDF $\rightarrow$ OCR Markdown Conversion $\rightarrow$ Hyperlink Injection $\rightarrow$ Parsing $\rightarrow$ Normalization $\rightarrow$ ATC Compliance Analysis $\rightarrow$ SQLite Storage $\rightarrow$ ChromaDB Vector Indexing**.

### A. Scrape a Specific Single Bid End-to-End
Searches for a specific tender on GeM, downloads its PDF, converts it via OCR, extracts compliance terms, saves artifacts to `downloads/<bid_no>/`, and indexes it into the database & vector store:
```powershell
python main.py --bid "GEM/2026/B/7768206"
```

### B. Run a Full Scrape Pass Across All Categories (Once)
Scrapes active tenders across all configured bid categories (Product, Service, BOQ, Custom, etc.) up to `TARGET_PER_TYPE`, updates database and ChromaDB, and exits:
```powershell
python main.py --once
```

### C. Run Continuous Scheduled Scraping (Daemon Loop)
Launches the automated background scraping daemon that executes every `SCRAPE_INTERVAL_MINUTES` (configured in `.env`, default: every 60 minutes):
```powershell
python main.py
```
*(Press `Ctrl + C` anytime to shut down gracefully).*

---

## 🧹 2. Database & Storage Cleaning Commands

Use these commands to clear databases, purge downloaded files, or reset the environment to a clean slate.

| Task | Command | What Gets Removed |
| :--- | :--- | :--- |
| **Clear SQLite Database Only** | `python main.py --clean-db` | `storage/gem_bids.db`<br/>`storage/gem_bids.json` |
| **Clear ChromaDB Vector Store Only** | `python main.py --clean-chroma` | `storage/chroma_db/` |
| **Clear Downloaded PDFs & Folders** | `python main.py --clean-downloads` | `downloads/*` |
| **Clear All Log Files** | `python main.py --clean-logs` | `logs/*` |
| **Standard Reset (DB + ChromaDB)** | `python main.py --reset` | `storage/gem_bids.db`<br/>`storage/gem_bids.json`<br/>`storage/chroma_db/`<br/>`output_md/` |
| **Complete Wipe / Factory Reset** | `python main.py --reset-all`<br/>*(or `--purge`)* | `storage/`<br/>`downloads/`<br/>`logs/`<br/>`output_md/` |

#### Examples:
```powershell
# Reset only the vector database before rebuilding embeddings:
python main.py --clean-chroma

# Reset only SQLite database:
python main.py --clean-db

# Clean slate for fresh test runs (DB + ChromaDB):
python main.py --reset

# Full purge of all downloads, logs, and databases:
python main.py --reset-all
```

---

## 📊 3. Database & System Inspection Commands

Inspect how many tenders are stored, how many vector chunks are indexed, and query records.

### A. View Summary System Statistics
Displays total bids in SQLite, new/unseen bids count, ChromaDB chunk count, and storage paths:
```powershell
python main.py --stats
```

### B. Direct SQLite Database Inspection (One-Liners)
Quick commands to query the database directly:

```powershell
# Count total tenders in SQLite:
python -c "import sqlite3; c=sqlite3.connect('storage/gem_bids.db'); print('Total bids:', c.execute('SELECT COUNT(*) FROM bids').fetchone()[0])"

# View the 5 most recent bids with department and value:
python -c "import sqlite3; c=sqlite3.connect('storage/gem_bids.db'); [print(f'{r[0]} | {r[1]} | ₹{r[2]}') for r in c.execute('SELECT bid_no, department, estimated_value FROM bids ORDER BY id DESC LIMIT 5').fetchall()]"

# Export all SQLite records to JSON manually:
python -c "from storage.database import BidDatabase; BidDatabase().export_json()"
```

### C. ChromaDB Vector Store Inspection
```powershell
# View ChromaDB collection stats and total indexed chunks:
python -c "from rag.vector_store import stats; print(stats())"
```

---

## 📋 4. ATC Compliance Analysis Commands

Extract the 5-section procurement compliance checklist (**Standard Documents, Clarified ATC Uploads, Exemption Proofs, Physical Submissions, Key Commercial Terms**) using AI:

### A. Analyze a Specific Tender Markdown
```powershell
# Analyze tender with medical & commercial clauses:
python main.py --analyze-atc "ATC EXTRACTOR/TEST_MARKDOWNS/GEM_2025_B_6904960"

# Analyze defense equipment tender:
python main.py --analyze-atc "ATC EXTRACTOR/TEST_MARKDOWNS/GEM_2026_B_7495766"
```
> **Output:** Writes `<bid_no>_ATC.md` directly into the tender directory and displays counts for all 5 compliance categories in the terminal.

### B. Batch Analyze All Downloaded Tenders
Analyzes every tender inside the `downloads/` directory:
```powershell
python main.py --analyze-atc "downloads"
```

---

## 🔍 5. Hybrid RAG & Question Answering Commands

Search tenders and query specific contract requirements using **BAAI/bge-base-en-v1.5 Dense Embeddings + BM25 Sparse Search + BAAI/bge-reranker-base Cross-Encoder**.

### A. Ask a Specific Compliance Question
```powershell
python main.py --ask "What are the exemption rules and documents required for MSEs in the medical analyzer bid?"
```

```powershell
python main.py --ask "What is the warranty period and SLA penalty for the medical analyzer tender?"
```

```powershell
python main.py --ask "What are the EMD requirements and advisory bank details?"
```

### B. Catalog Search & Filter
```powershell
# Broad search across all tenders:
python main.py --ask "What bids are there for desktop computers?"

# Filter search results by Product Type:
python main.py --ask "desktop computer" --filter product_type=Product
```

### C. Interactive Terminal Chat Session
Chat continuously with your tender catalog in real-time:
```powershell
python main.py --chat
```
* Type any question directly: `"Show me medical bids"`, `"What are the payment terms?"`
* Filter in chat: `f:product_type=Product desktop computer`
* Search only (no LLM): `/search desktop computer`
* Exit: `exit` or `quit`

### D. Re-index All Bids into Vector Store (Self-Healing)
Clears and re-indexes all tenders from SQLite into ChromaDB with fresh chunking and embeddings:
```powershell
python main.py --reindex
```

---

## 🧪 6. Automated Verification Test Suites

Run these commands to verify that all modules are working without issues:

### A. Master Verification Suite
Runs unit and integration tests across Data Normalizer, Core Parser, ATC Extractor, SQLite, ChromaDB, and Hybrid RAG:
```powershell
python test_all_phases.py
```

### B. Pluggable OCR Architecture Test Suite
Verifies provider factory resolution, pricing/costing engine, Mistral HTML table substitution, and parser compatibility:
```powershell
python test_ocr_providers.py
```

---

## 🌐 7. OCR Provider Configuration & Costing

You can switch the OCR provider anytime by editing `OCR_PROVIDER` in `Scrapper & RAG Pipeline/.env`:

```bash
# Options: mistral | gemini | openai | mineru
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

### Provider Comparison:

| Provider | Model | Unit Pricing (USD) | Approx. Cost (10-Page Bid) | Hardware Requirement |
| :--- | :--- | :--- | :--- | :--- |
| **Mistral OCR** *(Recommended)* | `mistral-ocr-3-0` | **\$1.00 / 1,000 pages** | **~\$0.010** (~₹0.86) | ❌ Zero GPU (Cloud API) |
| **Google Gemini** | `gemini-2.5-flash` | **\$0.075 / 1M in**, **\$0.30 / 1M out** | **~\$0.001 – \$0.003** (~₹0.15) | ❌ Zero GPU (Cloud API) |
| **OpenAI ChatGPT** | `gpt-4o-mini` | **\$0.15 / 1M in**, **\$0.60 / 1M out** | **~\$0.003 – \$0.006** (~₹0.40) | ❌ Zero GPU (Cloud API) |
| **Mineru VLM** | Local GPU vLLM | **\$0.00 API cost** | **\$0.00** | ✅ GPU with 4GB+ VRAM |

---

## 📌 8. Quick Task-to-Command Reference

| What You Want to Do | Exact Command to Run |
| :--- | :--- |
| **Scrape a specific tender** | `python main.py --bid "GEM/2026/B/7768206"` |
| **Run a single full scrape pass** | `python main.py --once` |
| **Run continuous hourly scraper** | `python main.py` |
| **Check database & vector stats** | `python main.py --stats` |
| **Ask a compliance question** | `python main.py --ask "What are the exemption rules for MSEs?"` |
| **Start interactive terminal chat** | `python main.py --chat` |
| **Extract ATC checklist from a bid** | `python main.py --analyze-atc "ATC EXTRACTOR/TEST_MARKDOWNS/GEM_2025_B_6904960"` |
| **Batch extract ATC for all bids** | `python main.py --analyze-atc "downloads"` |
| **Re-index all bids into vector store** | `python main.py --reindex` |
| **Clear SQLite database only** | `python main.py --clean-db` |
| **Clear ChromaDB vector store only** | `python main.py --clean-chroma` |
| **Clear downloaded PDFs only** | `python main.py --clean-downloads` |
| **Clear logs only** | `python main.py --clean-logs` |
| **Reset DB + ChromaDB** | `python main.py --reset` |
| **Factory Reset (Wipe everything)** | `python main.py --reset-all` |
| **Run full automated test suite** | `python test_all_phases.py` |
| **Run OCR architecture test suite** | `python test_ocr_providers.py` |
| **View CLI help menu** | `python main.py --help` |
