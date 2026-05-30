# GeM Bid Scraper + RAG Pipeline

## Project Structure

```
GeM Tender/
├── main.py                    ← entry point (all commands)
├── requirements.txt
├── .env                       ← all config values (copy from .env.example)
├── config/
│   └── settings.py            ← loads .env, exposes all settings
├── core/
│   ├── browser.py             ← Playwright stealth browser + ongoing-bids filter
│   └── parser.py              ← PDF extraction + card-based date scraping
├── pipeline/
│   ├── scraper.py             ← one full scrape run (active bids only)
│   └── scheduler.py           ← hourly loop + new bid alerts
├── storage/
│   └── database.py            ← SQLite dedup + JSON export + auto RAG index
├── rag/
│   ├── embedder.py            ← sentence-transformers (local, no API key)
│   ├── vector_store.py        ← ChromaDB + hybrid search (semantic + keyword)
│   ├── llm.py                 ← OpenAI / Ollama / retrieval-only with score breakdown
│   └── query_engine.py        ← public RAG interface + smart top_k + exit detection
├── utils/
│   ├── antibot.py             ← delays, UA rotation, stealth launch options
│   └── logger.py              ← rotating file + console logs
├── downloads/                 ← PDFs (auto-created)
├── logs/                      ← rotating log files (auto-created)
└── storage/
    ├── gem_bids.db            ← SQLite (auto-created)
    ├── gem_bids.json          ← JSON export (auto-created)
    └── chroma_db/             ← ChromaDB vector store (auto-created)
```

---

## Setup

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Install Tesseract (OCR fallback for scanned PDFs)
- **Windows**: https://github.com/UB-Mannheim/tesseract/wiki
- **Linux**:   `sudo apt install tesseract-ocr poppler-utils`
- **Mac**:     `brew install tesseract poppler`

### 3. (Optional) Install Ollama for local LLM answers
```bash
# Install from https://ollama.com then:
ollama pull llama3
```

### 4. Configure `.env`
Copy `.env.example` to `.env` and fill in your values. All settings have sensible defaults.

---

## All Commands

```bash
# Continuous hourly scrape loop (production)
python main.py

# Single scrape run (testing / cron)
python main.py --once

# Show DB + vector store stats
python main.py --stats

# Ask a question (RAG query)
python main.py --ask "Show me IT equipment bids above 10 lakh"

# Ask with a metadata filter
python main.py --ask "laptop bids" --filter product_type=Product
python main.py --ask "maintenance bids" --filter "bid_type=Service Bid/RAs"

# Interactive chat mode
python main.py --chat

# Rebuild vector store from existing SQLite DB
python main.py --reindex
```

### Chat mode commands
Once inside `--chat`:

| Command | Description |
|---|---|
| `<question>` | Hybrid search + LLM answer |
| `f:<key>=<value> <question>` | Search with metadata filter |
| `/search <question>` | Retrieval only, no LLM — shows item names + scores |
| `quit` / `bye` / `exit` / `done` | Exit chat |

---

## Scraper Behaviour

### Active Bids Only
The scraper applies the **"Ongoing Bids/RA"** filter on the GeM portal before collecting cards. This means only currently open/active bids are scraped — expired or closed bids are skipped automatically.

This is handled by `browser.select_ongoing_bids()` which clicks the "Ongoing Bids/RA" checkbox after selecting each bid type filter.

### Date Accuracy
Bid dates (`start_date`, `end_date`) are scraped directly from the **card HTML** on the listing page, not from the PDF. Card dates are more reliable because:
- PDFs sometimes contain incorrect or missing date fields
- Card HTML always shows the portal's authoritative start/end timestamps
- Card dates are in `DD-MM-YYYY HH:MM AM/PM` format and are converted to 24-hour `DD-MM-YYYY HH:MM:SS`

PDF dates are used only as a fallback when card dates are unavailable.

### Bid Types Scraped
```
Product Bid/RAs
Service Bid/RAs
Bid To RAs
Product Custom Bid/RAs
BOQ Bids
Rate Contract Bids
Global Tender
Limited Tender
Single Tender
```

---

## RAG Configuration (`.env` / `config/settings.py`)

| Setting | Default | Description |
|---|---|---|
| `RAG_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Local embedding model (no API key) |
| `RAG_LLM_PROVIDER` | `ollama` | `ollama` / `openai` / `""` (retrieval only) |
| `OLLAMA_MODEL` | `llama3` | Ollama model name |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model (if using OpenAI) |
| `RAG_TOP_K` | `5` | Unique bids returned per query |
| `RAG_CHUNK_SIZE` | `800` | Characters per text chunk |
| `RAG_CHUNK_OVERLAP` | `100` | Overlap between consecutive chunks |

### LLM Provider options

| Provider | Cost | Setup |
|---|---|---|
| `ollama` | Free, local | Install Ollama + `ollama pull llama3` |
| `openai` | Paid API | Set `OPENAI_API_KEY` in `.env` |
| `""` (empty) | Free | No LLM — returns formatted retrieval results with score breakdown |

---

## How RAG Works

```
User question
     │
     ▼
Embed query (sentence-transformers, local)
     │
     ▼
ChromaDB vector search → top-K*4 raw chunks (over-fetch for dedup)
     │
     ├── Semantic score  = 1 - cosine_distance   (60% weight)
     └── Keyword score   = TF-IDF field matching  (40% weight)
                │
                ▼
         Hybrid score = (semantic × 0.6) + (keyword × 0.4)
                │
                ▼
     Deduplicate by bid_no → top-K unique bids
                │
                ▼
     LLM (Ollama/OpenAI) generates answer  OR  retrieval-only output
                │
                ▼
     Answer + source bids with relevance scores
```

Every new bid scraped is **automatically indexed** into ChromaDB via `database.upsert()`.
No manual step needed — scrape → index → query all happen in one pipeline.

---

## Hybrid Scoring

The search combines two signals:

| Signal | Weight | What it captures |
|---|---|---|
| Semantic similarity | 60% | Meaning, intent, synonyms |
| Keyword matching | 40% | Exact words in item name, dept, type |

**Field weights for keyword scoring:**

| Field | Weight |
|---|---|
| `full_item_name` | 3.0 |
| `department` | 1.5 |
| `bid_type` | 1.0 |
| `product_type` | 1.0 |

When using retrieval-only mode (`RAG_LLM_PROVIDER=""`), each result shows a full score breakdown:
```
Overall Score : 72%
  • Semantic (60%)  : 85%
  • Keyword  (40%)  : 52%
```

---

## Query Engine Features

### Smart Top-K Selection
The query engine automatically adjusts how many results to fetch based on query intent:

| Intent | Example | top_k |
|---|---|---|
| Listing intent | "show all bids", "list every product bid", "how many bids" | max(default, 15) |
| Focused lookup | "find bid GEM/2024/B/123", "specific bid" | max(1, default // 2) |
| Default | "IT hardware bids" | default (5) |

### Exit Detection
In `--chat` mode, exit words are checked **before** any query processing. Supported exit words: `quit`, `exit`, `q`, `bye`, `goodbye`, `stop`, `close`, `end`, `done`, `ok bye`.

### /search Command
In chat mode, `/search <question>` performs retrieval only (no LLM) and displays:
- Bid number
- Full item name (from metadata, not raw chunk text)
- End date
- Hybrid score

---

## Example Queries

```bash
python main.py --ask "Find laptop or computer bids from NIC"
python main.py --ask "Which bids are ending this month?"
python main.py --ask "Service bids above 50 lakh" --filter product_type=Service
python main.py --ask "Global tenders in defence or military"
python main.py --ask "Show BOQ bids from Gujarat"
python main.py --ask "List all ongoing product bids"
```

---

## JSON Output Fields

```json
{
  "bid_type":        "Product Bid/RAs",
  "product_type":    "Product",
  "bid_no":          "GEM/2026/B/7382409",
  "ra_no":           "GEM/2026/R/1234567",
  "full_item_name":  "All in One PC (V2) (Q2)",
  "quantity":        "200",
  "department":      "Department Of Electronics And Information Technology",
  "start_date":      "11-12-2025 16:30:00",
  "end_date":        "11-01-2026 16:00:00",
  "estimated_value": "13000000",
  "bid_packet_type": "Two Packet Bid",
  "document_url":    "https://bidplus.gem.gov.in/showbidDocument/...",
  "corrigendum_url": "",
  "first_seen":      "2026-05-25T10:00:00",
  "last_seen":       "2026-05-25T11:00:00",
  "is_new":          1
}
```

> `full_pdf_text` is stored in SQLite but stripped from the JSON export to keep file size manageable.

---

## Running as a Background Service (Linux)

```ini
# /etc/systemd/system/gem-scraper.service
[Unit]
Description=GeM Bid Scraper
After=network.target

[Service]
WorkingDirectory=/path/to/gem_tender
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable gem-scraper
sudo systemctl start gem-scraper
```

## Running with Cron (alternative)

```bash
# Every hour — scrape active bids + auto-index new ones into RAG
0 * * * * cd /path/to/gem_tender && python main.py --once >> logs/cron.log 2>&1
```

---

## Logs

Each module writes to its own rotating log file in `logs/`:

| File | Module |
|---|---|
| `main.log` | Entry point |
| `scraper.log` | Scrape runs |
| `scheduler.log` | Scheduler loop |
| `browser.log` | Playwright browser |
| `parser.log` | PDF + card parsing |
| `database.log` | SQLite operations |
| `embedder.log` | Embedding model |
| `vector_store.log` | ChromaDB operations |

Logs rotate at 5 MB, keeping 5 backups per file.
