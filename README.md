# GeM Bid Scraper + RAG Pipeline

## Project Structure

```
gem_scraper/
├── main.py                    ← entry point (all commands)
├── requirements.txt
├── config/
│   └── settings.py            ← ALL config in one place
├── core/
│   ├── browser.py             ← Playwright stealth browser
│   └── parser.py              ← PDF extraction + field parsing
├── pipeline/
│   ├── scraper.py             ← one full scrape run
│   └── scheduler.py           ← hourly loop + new bid alerts
├── storage/
│   └── database.py            ← SQLite dedup + JSON export
├── rag/
│   ├── embedder.py            ← sentence-transformers (local)
│   ├── vector_store.py        ← ChromaDB wrapper
│   ├── llm.py                 ← OpenAI / Ollama / retrieval-only
│   └── query_engine.py        ← public RAG interface + CLI
├── utils/
│   ├── antibot.py             ← delays, UA rotation, stealth
│   └── logger.py              ← rotating logs
├── downloads/                 ← PDFs (auto-created)
├── logs/                      ← rotating log files (auto-created)
└── storage/
    ├── gem_bids.db            ← SQLite (auto-created)
    ├── gem_bids.json          ← JSON export (auto-created)
    └── chroma_db/             ← vector store (auto-created)
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

# Ask with a filter
python main.py --ask "laptop bids" --filter product_type=Product
python main.py --ask "maintenance bids" --filter bid_type=Service Bid/RAs

# Interactive chat mode
python main.py --chat

# Rebuild vector store from existing SQLite DB
python main.py --reindex
```

---

## RAG Configuration (config/settings.py)

| Setting | Default | Description |
|---|---|---|
| `RAG_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Local embedding model (no API key) |
| `RAG_LLM_PROVIDER` | `ollama` | `ollama` / `openai` / `""` (retrieval only) |
| `OLLAMA_MODEL` | `llama3` | Ollama model name |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model (if using OpenAI) |
| `RAG_TOP_K` | `5` | Chunks retrieved per query |
| `RAG_CHUNK_SIZE` | `800` | Characters per chunk |
| `RAG_CHUNK_OVERLAP` | `100` | Overlap between chunks |

### LLM Provider options

| Provider | Cost | Setup |
|---|---|---|
| `ollama` | Free, local | Install Ollama + `ollama pull llama3` |
| `openai` | Paid API | Set `OPENAI_API_KEY` env variable |
| `""` (empty) | Free | No LLM — returns formatted retrieval results |

---

## How RAG Works

```
User question
     │
     ▼
Embed query (sentence-transformers, local)
     │
     ▼
ChromaDB vector search → top-K relevant chunks
     │
     ▼
LLM (Ollama/OpenAI) generates answer from chunks
     │
     ▼
Answer + source bids with relevance scores
```

Every new bid scraped is **automatically indexed** into ChromaDB.
No manual step needed — scrape → index → query all happen in one pipeline.

---

## Example Queries

```bash
python main.py --ask "Find laptop or computer bids from NIC"
python main.py --ask "Which bids are ending this month?"
python main.py --ask "Service bids above 50 lakh" --filter product_type=Service
python main.py --ask "Global tenders in defence or military"
python main.py --ask "Show BOQ bids from Gujarat"
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
  "end_date":        "11-12-2025 16:00:00",
  "estimated_value": "13000000",
  "bid_packet_type": "Two Packet Bid",
  "document_url":    "https://bidplus.gem.gov.in/showbidDocument/...",
  "corrigendum_url": "",
  "first_seen":      "2026-05-25T10:00:00",
  "last_seen":       "2026-05-25T11:00:00",
  "is_new":          1
}
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
# Every hour — scrape + auto-index new bids into RAG
0 * * * * cd /path/to/gem_scraper && python main.py --once >> logs/cron.log 2>&1
```
