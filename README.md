# GeM Bid Scraper + Mineru VLM & Hybrid RAG Pipeline

> **Last Updated:** August 2026  
> **Status:** Production-ready GeM Bid Scraper & RAG System with Mineru VLM document parsing, PyMuPDF hyperlink extraction, and BGE + BM25 + Cross-Encoder Reranker hybrid search.

---

## 🏗 System Overview & Architecture

```
gem_scraper/
├── main.py                           ← Entry point (all CLI commands)
├── MINERU_MARKDOWN_PASER.py          ← Mineru VLM & Docling HTML/Markdown structured parser
├── requirements.txt                  ← Python dependencies & Mineru package URL
├── .env                              ← Configuration (copy from .env.example)
├── .gitignore                        ← Git ignore rules
├── sync_to_github.sh                 ← GitHub sync automation script
├── config/
│   ├── __init__.py
│   └── settings.py                  ← Central configuration (.env loader & RAG parameters)
├── core/
│   ├── __init__.py
│   ├── browser.py                   ← Playwright stealth browser manager
│   │                                   • Anti-bot delays & User-Agent rotation
│   │                                   • "Ongoing Bids/RA" active bid filter
│   │                                   • Advanced Search by single Bid No
│   │                                   • Stealth JS injection (hides webdriver)
│   └── parser.py                    ← HTML card parser + Mineru Markdown field parser
│                                       • get_dates_from_card() (24h conversion)
│                                       • get_full_item_name_from_card() (Bootstrap popovers)
│                                       • parse_bid_data() (10-section structured schema)
│                                       • _expand_table_grid() (rowspan/colspan safe tables)
├── pipeline/
│   ├── __init__.py
│   ├── scraper.py                   ← Scraping & Mineru VLM processing orchestrator
│   │                                   • AsyncWorker & ProgressTimer spinner
│   │                                   • Mineru VLM document conversion (Zero Save Mode)
│   │                                   • Artifact generation (.html, .pdf, .md, .json)
│   │                                   • SQLite upsert & ChromaDB vector store indexing
│   └── scheduler.py                 ← Hourly background loop with SIGINT/SIGTERM handlers
├── storage/
│   ├── __init__.py
│   ├── database.py                  ← SQLite storage + deduplication + json export
│   ├── gem_bids.db                  ← SQLite database (auto-created)
│   ├── gem_bids.json                ← Stripped JSON export (auto-updated)
│   └── chroma_db/                   ← ChromaDB vector store directory
├── rag/
│   ├── __init__.py
│   ├── embedder.py                  ← Vector embedding encoder
│   │                                   • BAAI/bge-base-en-v1.5 (local offline mode)
│   │                                   • Metadata card chunking + text sliding window
│   │                                   • BGE retrieval query instruction prefixing
│   ├── vector_store.py              ← Hybrid search pipeline
│   │                                   • BGE Dense similarity search
│   │                                   • BM25Okapi sparse keyword retrieval
│   │                                   • Reciprocal Rank Fusion (RRF)
│   │                                   • BAAI/bge-reranker-base CrossEncoder with Sigmoid
│   │                                   • Score filtering (70% relative threshold)
│   ├── llm.py                       ← LLM answer generation
│   │                                   • Ollama (llama3) / OpenAI (gpt-4o-mini) / Retrieval-only
│   │                                   • Zero-hallucination prompt & N/A field handling
│   └── query_engine.py              ← Public RAG query interface
│                                       • Smart top_k selection based on intent
│                                       • Exit word detection
│                                       • Metadata filtering (f:key=value)
│                                       • /search retrieval-only mode
├── utils/
│   ├── __init__.py
│   ├── antibot.py                   ← Human-like delays, UA rotation, mouse movement
│   ├── pdf_hyperlinks.py            ← PyMuPDF clickable URI extraction & Markdown injection
│   └── logger.py                    ← Rotating console & file logging
├── STANDLONE TEST SCRIPTS/            ← Standalone scraper testing & evaluation scripts
│   ├── TEST_STANDALONE_SCRAPPER.py
│   ├── TEST_STANDALONE_SCRAPPER_MULTI_ITEM_ONLY.py
│   ├── TEST_STANDALONE_SCRAPPER_SCRAPE_PARTICULAR_BID.py
│   └── TEST_STANDALONE_SCRAPPER_WITH_EVAL_METHODS_SPLIT_REPORT.py
├── downloads/                       ← Per-bid artifact storage: downloads/<safe_bid_no>/
├── logs/                            ← Rotating log files
└── Documentation/
    ├── README.md                    ← Main project documentation (this file)
    └── Mineru_README.md             ← Mineru VLM & document conversion documentation
```

---

## ⚡ Quick Start

### 1. Install Dependencies
```bash
# Python 3.10+ recommended
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure `.env`
```bash
cp .env.example .env
# Adjust parameters in .env if needed (pre-configured with optimal defaults)
```

### 3. (Optional) Setup LLM Provider
- **Ollama (Free, local)**: Download from [ollama.com](https://ollama.com) and pull a model:
  ```bash
  ollama pull llama3
  ```
- **OpenAI**: Set `OPENAI_API_KEY` in `.env` and set `RAG_LLM_PROVIDER=openai`.
- **Retrieval-Only Mode**: Set `RAG_LLM_PROVIDER=""` (no LLM required; returns structured score breakdowns).

---

## 💻 All CLI Commands

```bash
# 1. Continuous scheduled hourly scrape loop (default production mode)
python main.py

# 2. Single scrape run (scrapes all 9 categories once and exits)
python main.py --once

# 3. Targeted search and scrape for a single specific Bid / RA Number
python main.py --bid "GEM/2026/B/7768206"

# 4. Ask a question using the RAG Pipeline
python main.py --ask "Show me IT equipment bids above 10 lakh"

# 5. Ask a question with metadata filters
python main.py --ask "laptop bids" --filter product_type=Product
python main.py --ask "maintenance services" --filter "bid_type=Service Bid/RAs"

# 6. Interactive RAG Chat Session
python main.py --chat

# 7. Re-index SQLite database records into ChromaDB vector store
python main.py --reindex

# 8. Display database records and ChromaDB chunk statistics
python main.py --stats

# 9. Clean reset of SQLite DB, JSON exports, and vector store
python main.py --reset
```

### Interactive Chat Mode (`python main.py --chat`)
Inside `--chat` mode, the following commands are supported:

| Command | Action |
|---|---|
| `<question>` | Executes hybrid search + LLM answer generation |
| `f:<key>=<value> <question>` | Executes metadata-filtered search and answer generation |
| `/search <question>` | Retrieval-only search (shows matching bids, item titles, and rerank scores) |
| `quit` / `bye` / `exit` / `done` | Cleanly exits chat session |

---

## 🔍 Scraper & Mineru VLM Pipeline Features

### 1. Active Bids Only Filtering
The scraper automatically applies the **"Ongoing Bids/RA"** filter on the GeM portal before collecting bid cards, skipping closed or expired tenders.

### 2. High-Accuracy Card Date & Metadata Scraping
- Start and end dates are extracted directly from the listing page card HTML to guarantee accuracy.
- 12-hour AM/PM timestamps are converted to standardized 24-hour `DD-MM-YYYY HH:MM:SS`.
- Complete item names are retrieved from Bootstrap popover attributes (`data-content`, `data-original-title`) to avoid truncated title text.

### 3. Mineru VLM Document Conversion
- High-accuracy PDF-to-Markdown conversion powered by `Mineru_Document_To_Markdown`.
- Runs in **Zero Save Mode** (`output_dir=None`) with vLLM acceleration (`async_start_vllm_server`).
- GPU-tuned for RTX 2050 (4 GB VRAM) with `batch_size=16`, `max_gpu_util=0.78`, and `model_len=4096`.

### 4. PyMuPDF Hyperlink Extraction
- Extracts all clickable URI hyperlinks and visible anchor texts directly from the downloaded PDF.
- Injects a `## Hyperlinks` section into the Markdown text so URLs are preserved in vector embeddings and searchable via BM25 / dense retrieval.

### 5. Multi-Artifact Per-Bid Storage
For every scraped bid, a dedicated directory `downloads/<safe_bid_no>/` is created containing 4 output artifacts:
1. `<safe_bid_no>.html`: Raw HTML card snippet.
2. `<safe_bid_no>.pdf`: Downloaded Bid PDF (and optional `<safe_bid_no>_RA.pdf`).
3. `<safe_bid_no>.md`: Mineru VLM generated Markdown.
4. `<safe_bid_no>.json`: Complete unified JSON schema artifact containing `_id`, `bid`, `card`, `pdf`, `hyperlinks`, and `full_pdf_text`.

---

## 🧠 Hybrid RAG Retrieval Architecture

```
User Query
    │
    ├── 1. Dense Retrieval (BAAI/bge-base-en-v1.5 embeddings with BGE Query Prompt)
    ├── 2. Sparse Retrieval (BM25Okapi keyword search over metadata-enriched text)
    │
    ▼
Reciprocal Rank Fusion (RRF)
    │
    ▼
Cross-Encoder Reranking (BAAI/bge-reranker-base with Sigmoid logit conversion)
    │
    ▼
Relative Score Filtering (70% top-score cutoff) & Bid Deduplication
    │
    ▼
LLM Answer Generation (Ollama / OpenAI / Retrieval Formatter)
```

### Hybrid Scoring Rationale
- **Dense Embedding**: `BAAI/bge-base-en-v1.5` (384/768-dim, local offline mode) captures semantic context and intent.
- **Sparse Keyword Search**: `BM25Okapi` ensures exact keyword matches for bid numbers, item categories, and department titles.
- **Cross-Encoder Reranker**: `BAAI/bge-reranker-base` re-ranks candidate chunks, providing high-precision relevance scores.
- **Weighted Final Score**: `(Reranker × 0.6) + (Dense × 0.25) + (BM25 × 0.15)`.

---

## 📊 Standard Output Schema (`downloads/<safe_bid_no>/<safe_bid_no>.json`)

```json
{
    "_id": "GEM_2026_B_7768206",
    "bid": {
        "bid_no": "GEM/2026/B/7768206",
        "ra_no": "",
        "bid_type": "Product Bid/RAs",
        "product_type": "Product",
        "base_type": "PRODUCT",
        "process_kind": "CATALOGUE"
    },
    "card": {
        "items": [
            {
                "name": "Submersible Water Pump Set",
                "quantity": 50
            }
        ],
        "departments": [
            {
                "name": "Public Health Engineering Department",
                "address": "Jaipur, Rajasthan",
                "pincode": "302001"
            }
        ],
        "start_datetime": "01-08-2026 10:00:00",
        "end_datetime": "21-08-2026 15:00:00",
        "bid_pdf_url": "https://bidplus.gem.gov.in/showbiddocument/...",
        "ra_pdf_url": ""
    },
    "pdf": {
        "timing": {},
        "departments": {},
        "items": {},
        "evaluation": {},
        "documents": {},
        "consignees": [],
        "relaxations": {},
        "financials": {},
        "terms": {}
    },
    "hyperlinks": [
        {
            "page": 1,
            "text": "GeM Portal Guidelines",
            "url": "https://gem.gov.in/guidelines",
            "source": "bid"
        }
    ],
    "full_pdf_text": "..."
}
```

---

## 📑 Logs

Logs are automatically recorded and rotated (5 MB per file, 5 backups) in `logs/`:

| Log File | Module |
|---|---|
| `main.log` | CLI dispatcher & command logging |
| `scraper.log` | Scraper & Mineru VLM conversion progress |
| `scheduler.log` | Scheduler background loop & OS signals |
| `browser.log` | Playwright browser automation |
| `parser.log` | HTML card & PDF field extraction |
| `database.log` | SQLite transactions & JSON exports |
| `embedder.log` | SentenceTransformer model loading |
| `vector_store.log` | ChromaDB, BM25, and CrossEncoder operations |
