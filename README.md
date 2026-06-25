# GeM Bid Scraper + RAG Pipeline

> **Last Updated:** June 2026
> **Branch:** v2 — Modular scraper / indexer / query architecture

A production system that scrapes active bids from the [Government e-Marketplace (GeM)](https://bidplus.gem.gov.in), stores them in MongoDB, embeds them into a vector store, and answers natural-language queries using hybrid RAG search.

---

## Architecture Overview

The system is split into three independent modules that communicate through MongoDB:

```
GeM Website                        External Tender API
    │                                      │
    ▼                                      ▼
┌─────────────────────────────────────────────────────────┐
│  scraper/          (any server — no GPU needed)         │
│  Playwright browser → PDF parser │ API client → parser  │
│                   ↘              ↙                      │
│                    MongoDB (Save)                       │
└─────────────────────────────────────────────────────────┘
              │  writes bids  (is_new=True)
              ▼
         MongoDB
              │  reads new bids
              ▼
┌─────────────────────────────────────────────────────────┐
│  indexer/          (GPU server recommended)             │
│  MongoDB → BGE embeddings → ChromaDB vector store       │
└─────────────────────────────────────────────────────────┘
              │  reads ChromaDB
              ▼
┌─────────────────────────────────────────────────────────┐
│  query/            (GPU server or separate machine)     │
│  Dense + BM25 + RRF + Cross-encoder reranker → answer   │
└─────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
gem_scraper/
│
├── main.py                      ← Unified entry point (all commands)
├── requirements.txt             ← All dependencies (universal install)
├── .env                         ← Configuration (never committed)
├── ARCHITECTURE.md              ← Detailed architecture + deploy guide
│
├── shared/                      ← Installed on ALL machines
│   ├── config/settings.py       ← Single source of config, reads .env
│   ├── storage/mongo_client.py  ← MongoDB read/write
│   ├── rag/embedder.py          ← BGE embedding model (shared by indexer+query)
│   └── utils/
│       ├── logger.py            ← Rotating file + console logging
│       └── antibot.py           ← Human-like delays, stealth browser options
│
├── scraper/                     ← Scraper module
│   ├── core/
│   │   ├── browser.py           ← Playwright stealth Chromium session
│   │   └── parser.py            ← PDF extraction + field parsing + sector classification
│   └── pipeline/
│       ├── scheduler.py         ← Timed loop (every N minutes)
│       ├── scraper.py           ← Per-bid-type scrape → save to MongoDB
│       ├── tender_api_client.py ← External tender API HTTP client
│       ├── tender_parser.py     ← Normalises active/result tender formats
│       └── tender_pipeline.py   ← Tender API orchestrator
│
├── indexer/                     ← Indexer module (GPU server)
│   └── rag/vector_store.py      ← ChromaDB WRITE: chunk → embed → upsert
│
├── query/                       ← Query module
│   └── rag/
│       ├── vector_store.py      ← ChromaDB READ: dense+BM25+RRF+reranker
│       ├── query_engine.py      ← RAG orchestration + auto-filter detection
│       └── llm.py               ← Ollama / OpenAI / retrieval-only output
│
├── downloads/                   ← Scraped PDFs (auto-created)
├── logs/                        ← Rotating log files (auto-created)
└── storage/
    └── chroma_db/               ← ChromaDB vector store (auto-created)
```

---

## Quick Start

### 1. Install Dependencies

```bash
# Python 3.10+
pip install -r requirements.txt
playwright install chromium
```

**Windows** — Tesseract OCR (for PDF fallback):
```bash
# Download installer: https://github.com/UB-Mannheim/tesseract/wiki
# Install to C:\Program Files\Tesseract-OCR\
```

**Linux:**
```bash
sudo apt install tesseract-ocr poppler-utils
```

### 2. Start MongoDB

```bash
# Local (default)
mongod --dbpath /data/db

# Or use MongoDB Atlas — set MONGO_URI in .env
```

### 3. Configure `.env`

```bash
cp .env  # edit with your values — all have sensible defaults
```

Key settings:

```env
MONGO_URI=mongodb://localhost:27017
RAG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
RAG_RERANKER_MODEL=BAAI/bge-reranker-large
RAG_LLM_PROVIDER=          # blank = retrieval-only, or: ollama / openai
TARGET_PER_TYPE=3           # bids to scrape per bid type per run
```

### 4. (Optional) Install Ollama for LLM answers

```bash
# Download from https://ollama.com
ollama pull llama3
# Then set in .env: RAG_LLM_PROVIDER=ollama
```

---

## All Commands

All commands go through the root `main.py`:

```bash
# ── Scraper ──────────────────────────────────────────────
python main.py --scrape --once          # single scrape run
python main.py --scrape                 # continuous loop (every 60 min)
python main.py --scrape --tender-active # fetch open tenders from external API
python main.py --scrape --tender-results# fetch awarded tenders from API
python main.py --scrape --tender-file path.json # load tenders from local file
python main.py --scrape --tender-stats  # tender collection stats
python main.py --scrape --stats         # MongoDB scraper stats

# ── Export ───────────────────────────────────────────────
python main.py --export                 # export all bids to output.json
python main.py --export --out my_file.json # export to a custom path

# ── Indexer ──────────────────────────────────────────────
python main.py --index --index-new      # embed only new (is_new=True) bids
python main.py --index --reindex-all    # rebuild entire vector store from scratch

# ── Query ────────────────────────────────────────────────
python main.py --query --ask "show me defence bids"
python main.py --query --ask "bids in Uttar Pradesh"
python main.py --query --ask "XLPE cable electrical tender"
python main.py --query --chat           # interactive chat mode

# ── Query with explicit filters ──────────────────────────
python main.py --query --ask "all bids" --filter sector="Defence and Security"
python main.py --query --ask "goods bids" --filter state="Uttar Pradesh"
python main.py --query --ask "services bids" --filter procurement_type=Services

# ── Stats ────────────────────────────────────────────────
python main.py --stats
```

---

## RAG Pipeline — How It Works

```
User query: "defence equipment bids"
        │
        ▼
1. Auto-filter detection
   • "bids in Uttar Pradesh"  → state=Uttar Pradesh
   • "information technology" → sector=Information Technology
   • "services tenders"       → procurement_type=Services
   (generic words like "services" in "printing services" do NOT trigger filters)
        │
        ▼
2. Dense retrieval (BGE embeddings, cosine similarity)
   → fetch top-40 chunks from ChromaDB
        │
        ▼
3. BM25 keyword retrieval (metadata fields only)
   → item name ×3 weight, sector, dept, bid_type, state
        │
        ▼
4. RRF fusion (Reciprocal Rank Fusion)
   → merge dense + BM25 rankings
        │
        ▼
5. Deduplicate by bid_no — always use chunk[0] (metadata card)
        │
        ▼
6. Cross-encoder reranker (bge-reranker-large)
   → score each (query, document) pair directly
   → drop results with rerank score < 0.55
        │
        ▼
7. Tail trim — drop bottom 20% if > 3 results
        │
        ▼
8. LLM (Ollama / OpenAI) or retrieval-only output
```

### Score Interpretation

The displayed `score` is the **cross-encoder reranker score** — the most meaningful signal:

| Score | Meaning |
|---|---|
| 85–100% | Strong specific match — query and item align precisely |
| 70–85% | Good match — correct category, item clearly relevant |
| 55–70% | Moderate — correct sector/dept but query is vague or broad |
| < 55% | Dropped — reranker judged it not relevant |

Broad queries like "show me defence bids" naturally score 65–72% — the reranker is **correctly** saying the match is sector-level, not item-level. More specific queries like "UV ozone environmental chamber" score 85%+.

---

## Configuration Reference

All settings are in `.env` and loaded by `shared/config/settings.py`:

### Scraper

| Setting | Default | Description |
|---|---|---|
| `TARGET_PER_TYPE` | `3` | Bids to collect per bid type per run |
| `MAX_EMPTY_PAGES` | `5` | Stop after N pages with no new bids |
| `SCRAPE_INTERVAL_MINUTES` | `60` | Scheduler loop interval |
| `GEM_BASE_URL` | `https://bidplus.gem.gov.in` | GeM portal base URL |

### RAG / Indexer / Query

| Setting | Default | Description |
|---|---|---|
| `RAG_EMBEDDING_MODEL` | `BAAI/bge-base-en-v1.5` | Embedding model (768-dim) |
| `RAG_RERANKER_MODEL` | `BAAI/bge-reranker-large` | Cross-encoder reranker |
| `RAG_USE_RERANKER` | `true` | Enable/disable reranker |
| `RAG_TOP_K` | `5` | Results returned per query |
| `RAG_FETCH_K` | `40` | Candidates fetched before reranking |
| `RAG_CHUNK_SIZE` | `800` | Characters per text chunk |
| `RAG_CHUNK_OVERLAP` | `100` | Overlap between chunks |
| `RAG_RERANKER_WEIGHT` | `0.60` | Reranker share of final score |
| `RAG_DENSE_WEIGHT` | `0.60` | Dense share of remaining weight |
| `RAG_BM25_WEIGHT` | `0.40` | BM25 share of remaining weight |
| `CHROMA_DIR` | `storage/chroma_db` | ChromaDB storage path |
| `CHROMA_COLLECTION` | `gem_bids` | Collection name |

### LLM

| Setting | Default | Description |
|---|---|---|
| `RAG_LLM_PROVIDER` | `""` | `ollama` / `openai` / `""` (retrieval-only) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3` | Ollama model name |
| `OPENAI_API_KEY` | `""` | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model |

### MongoDB

| Setting | Default | Description |
|---|---|---|
| `MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `MONGO_DB_NAME` | `gem_scraper` | Database name |
| `MONGO_BIDS_COLL` | `bids` | Bids collection |

---

## Bid Types Scraped

```
Product Bid/RAs       Service Bid/RAs       Bid To RAs
Product Custom Bid/RAs    BOQ Bids          Rate Contract Bids
Global Tender         Limited Tender        Single Tender
```

---

## Example Queries

```bash
# By item
python main.py --query --ask "XLPE cable electrical"
python main.py --query --ask "UV ozone environmental chamber"
python main.py --query --ask "300 TB storage data center"
python main.py --query --ask "proximity warning device mining"
python main.py --query --ask "stainless steel tube grade 304"

# By sector / category
python main.py --query --ask "defence equipment bids"
python main.py --query --ask "fire fighting system maintenance"
python main.py --query --ask "healthcare medical global tender"

# By location
python main.py --query --ask "bids in Uttar Pradesh"
python main.py --query --ask "tenders in Delhi"
python main.py --query --ask "goods tenders in Chhattisgarh"

# Combined
python main.py --query --ask "information technology bids in Tamil Nadu"
python main.py --query --ask "services tenders" --filter state="West Bengal"
```

---

## Logs

Each module writes to its own rotating log file in `logs/` (5 MB max, 5 backups):

| File | Module |
|---|---|
| `main.log` | Entry point |
| `scraper.log` | Scrape runs |
| `scheduler.log` | Scheduler loop |
| `browser.log` | Playwright browser |
| `parser.log` | PDF + card parsing |
| `mongo_client.log` | MongoDB operations |
| `embedder.log` | Embedding model |
| `vector_store.log` | ChromaDB operations |
| `query_engine.log` | Query pipeline |
| `llm.log` | LLM calls |

---

## Model Upgrade Options

| Component | Current | Upgrade | Notes |
|---|---|---|---|
| Embedding | `bge-base-en-v1.5` (400MB) | `bge-large-en-v1.5` (1.2GB) | Better vectors, needs reindex |
| Embedding | `bge-base-en-v1.5` | `bge-m3` (2GB) | Multilingual — handles Hindi PDF text |
| Reranker | `bge-reranker-large` (1.3GB) | `bge-reranker-v2-m3` | Best accuracy, multilingual |

To upgrade embedding model — change `.env` then reindex:

```bash
# .env
RAG_EMBEDDING_MODEL=BAAI/bge-m3

# Rebuild vector store with new model
python main.py --index --reindex-all
```

Reranker upgrade requires no reindex — just change `.env`:

```bash
RAG_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
```

---

## Running as a Background Service (Linux)

```ini
# /etc/systemd/system/gem-scraper.service
[Unit]
Description=GeM Bid Scraper
After=network.target

[Service]
WorkingDirectory=/path/to/gem_scraper
ExecStart=/usr/bin/python3 main.py --scrape
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable gem-scraper
sudo systemctl start gem-scraper
```

## Cron Alternative

```bash
# Every hour — scrape + index new bids
0 * * * * cd /path/to/gem_scraper && python main.py --scrape --once >> logs/cron.log 2>&1
5 * * * * cd /path/to/gem_scraper && python main.py --index --index-new >> logs/cron.log 2>&1
```

---

## Requirements

- Python 3.10+
- MongoDB 6.0+ (local or Atlas)
- `numpy<2.0` (torch 2.3.x requires NumPy 1.x)
- `chromadb>=0.5.4` (NumPy 2.x compatible)
- Playwright Chromium (`playwright install chromium`)
- ~2GB disk for embedding + reranker models (downloaded automatically on first run)
