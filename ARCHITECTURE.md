# GeM Scraper — Modular Architecture

## Directory Layout

```
gem_scraper/
│
├── shared/                     ← Installed on ALL machines (pip install -e .)
│   ├── config/
│   │   └── settings.py         ← Single source of config — reads .env
│   ├── storage/
│   │   └── mongo_client.py     ← MongoDB read/write (no RAG calls)
│   ├── utils/
│   │   ├── logger.py           ← Rotating file + console logger
│   │   └── antibot.py          ← Human-like delays, stealth browser options
│   └── rag/
│       └── embedder.py         ← SentenceTransformer model (shared by indexer+query)
│
├── scraper/                    ← Machine 1 (any server, no GPU needed)
│   ├── main.py                 ← Entry point
│   ├── requirements.txt        ← playwright, pymupdf, requests, pymongo
│   ├── .env                    ← MONGO_URI, GEM_BASE_URL, DOWNLOAD_DIR, ...
│   ├── core/
│   │   ├── browser.py          ← Playwright stealth Chromium session
│   │   └── parser.py           ← PDF text extraction + field parsing
│   └── pipeline/
│       ├── scheduler.py        ← Timed loop every N minutes
│       ├── scraper.py          ← Per-bid-type scrape → save to MongoDB
│       ├── tender_pipeline.py  ← External tender API orchestrator
│       ├── tender_api_client.py← HTTP pagination client
│       └── tender_parser.py    ← Normalises 2 API response formats
│
├── indexer/                    ← Machine 2: GPU server
│   ├── main.py                 ← Entry point
│   ├── requirements.txt        ← sentence-transformers, chromadb, rank-bm25, pymongo
│   ├── .env                    ← MONGO_URI, CHROMA_DIR, RAG_EMBEDDING_MODEL, ...
│   └── rag/
│       └── vector_store.py     ← ChromaDB WRITE: chunk → embed → store
│
└── query/                      ← Machine 2 (same GPU) or Machine 3
    ├── main.py                 ← Entry point
    ├── requirements.txt        ← sentence-transformers, chromadb, rank-bm25, openai/requests
    ├── .env                    ← CHROMA_DIR, RAG_*, OLLAMA_BASE_URL or OPENAI_KEY
    └── rag/
        ├── vector_store.py     ← ChromaDB READ: dense+BM25+RRF+reranker
        ├── query_engine.py     ← Orchestrates full RAG query pipeline
        └── llm.py              ← LLM provider (Ollama / OpenAI / fallback)
```

---

## Data Flow

```
GeM Website                        External Tender API
    │                                      │
    ▼                                      ▼
scraper/core/browser.py             scraper/pipeline/tender_api_client.py
(Playwright, downloads PDFs)        (Fetches JSON paginated data)
    │                                      │
    ▼                                      ▼
scraper/core/parser.py              scraper/pipeline/tender_parser.py
(extracts 35+ fields)               (Normalizes formats)
    │                                      │
    ▼                                      ▼
scraper/pipeline/scraper.py         scraper/pipeline/tender_pipeline.py
    │                                      │
    └─── saves bid dict (is_new=True) ─────┘
    ▼
MongoDB  ←────────────────────── shared/storage/mongo_client.py
    │
    │  (manual trigger or cron)
    ▼
indexer/main.py --index-new
    │  reads is_new=True bids from MongoDB
    │
    ▼
shared/rag/embedder.py           (build_bid_chunks → embed_texts)
    │  768-dim vectors (bge-base-en-v1.5)
    ▼
indexer/rag/vector_store.py      (ChromaDB upsert)
    │  marks bids is_new=False in MongoDB
    ▼
storage/chroma_db/

    │
    │  (user query)
    ▼
query/main.py --ask "..."
    │
    ▼
query/rag/query_engine.py
    ├── auto-detect filters (state/sector/status)
    ├── shared/rag/embedder.embed_query()
    ├── query/rag/vector_store.search()
    │     dense → BM25 → RRF → dedup → reranker
    └── query/rag/llm.py (Ollama / OpenAI)
          └── formatted answer + sources
```

---

## Why the RAG Call Was Removed from database.upsert()

The old `storage/database.py` called `rag.vector_store.upsert_bid()` inline
every time a bid was saved. This meant:

- The scraper machine had to have `sentence-transformers`, `chromadb`, and
  a 400MB AI model installed — even though scraping has nothing to do with AI.
- The embedding model blocked every scrape run for 60-90 seconds on cold start.
- You couldn't deploy the scraper on a cheap server without a GPU.

Now: scraper writes `{is_new: True}` to MongoDB. Indexer reads that flag
and handles embeddings independently on the GPU server. Clean separation.

---

## Deploy Commands

### Machine 1 — Scraper
```bash
cd scraper
cp .env.example .env   # fill in MONGO_URI
pip install -r requirements.txt
playwright install chromium

# Scrape GeM Portal
python ../main.py --scrape --once          # single run
python ../main.py --scrape                 # continuous loop

# Scrape Tender API
python ../main.py --scrape --tender-active
python ../main.py --scrape --tender-results

# Export
python ../main.py --export                 # exports bids to output.json
```

### Machine 2 — Indexer (GPU server)
```bash
cd indexer
cp .env.example .env   # fill in MONGO_URI, CHROMA_DIR
pip install -r requirements.txt

python main.py --index-new     # after each scraper run
python main.py --reindex-all   # rebuild from scratch
```

### Machine 2 — Query (same GPU server)
```bash
cd query
cp .env.example .env   # fill in CHROMA_DIR, LLM settings
pip install -r requirements.txt

python main.py --ask "show me open bids for printing"
python main.py --chat
```

### Install shared/ on all machines
```bash
# From the gem_scraper root:
pip install -e .    # if you add a setup.py
# OR add to PYTHONPATH:
export PYTHONPATH=/path/to/gem_scraper
```
