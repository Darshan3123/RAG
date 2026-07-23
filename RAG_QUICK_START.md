# GeM Bid RAG System — Quick Start Guide

> **Last Updated:** July 2026  
> **For:** First-time users, quick answers, command reference  
> See [README_RAG_DOCUMENTATION.md](README_RAG_DOCUMENTATION.md) for complete guide index

---

## What This System Does

1. **Scrapes GeM Portal** — Active bids only (via "Ongoing Bids/RA" filter)
2. **Extracts Bid Data** — PDFs + card HTML dates
3. **Builds Vector Database** — ChromaDB with embeddings
4. **Answers Questions** — Hybrid search (semantic + keyword) + optional LLM

---

## System At A Glance

```
PIPELINE:
  Scrape (active bids) → Parse PDFs + card dates → Store SQLite + ChromaDB
                              ↓
  Query → Embed → Hybrid search → Rank by relevance → LLM answer
```

### Key Numbers (Defaults)

| Parameter | Value | Impact |
|-----------|-------|--------|
| `RAG_TOP_K` | 5 | Unique bids per query |
| `RAG_CHUNK_SIZE` | 800 | Characters per chunk |
| `RAG_CHUNK_OVERLAP` | 100 | Overlap for context |
| Semantic weight | 0.6 | 60% of final score |
| Keyword weight | 0.4 | 40% of final score |

---

## The Scoring Formula (MOST IMPORTANT)

This is the heart of RAG relevance:

```
For each bid retrieved:

┌─────────────────────────────────────────────────┐
│ SEMANTIC TRACK                                  │
│ ─────────────────────────────────────────────── │
│ 1. Embed query + bid text using sentence-       │
│    transformers (384-dim vectors)               │
│ 2. Cosine similarity = closeness of vectors     │
│ 3. semantic_score = 1 - distance (0 to 1)       │
│    • 1.0 = perfect semantic match               │
│    • 0.0 = completely unrelated                 │
└─────────────────────────────────────────────────┘
              ↓
        ┌─────────────────────────────────────────┐
        │ KEYWORD TRACK                           │
        │ ─────────────────────────────────────── │
        │ 1. Split query into words               │
        │ 2. Remove stop words (the,for,and,etc.) │
        │ 3. Match in structured fields:          │
        │    • full_item_name    (weight: 3.0)    │
        │    • department        (weight: 1.5)    │
        │    • bid_type          (weight: 1.0)    │
        │    • product_type      (weight: 1.0)    │
        │ 4. keyword_score = Σ(matches × weights) │
        │    (normalized to 0-1)                  │
        └─────────────────────────────────────────┘
              ↓
  ┌────────────────────────────────────────────┐
  │ HYBRID SCORE (Final Ranking)               │
  │ ─────────────────────────────────────────  │
  │ hybrid = (semantic × 0.6) + (keyword × 0.4)│
  │                                             │
  │ Example:                                    │
  │ Semantic: 0.88, Keyword: 0.46              │
  │ Hybrid = (0.88 × 0.6) + (0.46 × 0.4)       │
  │        = 0.528 + 0.184 = 0.712 ← FINAL     │
  └────────────────────────────────────────────┘
```

**Real Example:**
```
Query: "Dell Laptop bids"

Bid A: "Dell Laptops from Tech Ministry" [actual item name]
  ├─ Semantic score: 0.92 (excellent match)
  ├─ Keyword score:  0.94 ("Dell" + "Laptop" found in item)
  └─ Hybrid: (0.92 × 0.6) + (0.94 × 0.4) = 0.928 ✓ TOP

Bid B: "Office Furniture from Tech Ministry"
  ├─ Semantic score: 0.45 (weak, about furniture)
  ├─ Keyword score:  0.30 (only "Tech" matches)
  └─ Hybrid: (0.45 × 0.6) + (0.30 × 0.4) = 0.390 ⬇ Lower
```

---

## Quick Command Reference

### Testing & Exploration

```bash
# Interactive chat (BEST for testing)
python main.py --chat

# In chat mode, try:
# You > show me laptop bids
# You > f:product_type=Product laptops
# You > /search IT equipment
# You > quit

# Single one-off query
python main.py --ask "IT hardware bids"

# Query with filter
python main.py --ask "laptops" --filter product_type=Product

# View system health
python main.py --stats

# Retrieval only (no LLM) — shows score breakdown
# First set in .env: RAG_LLM_PROVIDER=
python main.py --ask "laptops"
# Output: Each result shows Semantic %, Keyword %, Overall %
```

### Maintenance

```bash
# Rebuild vector store (after changing embedding model or chunk size)
python main.py --reindex

# Production continuous scrape (runs hourly)
python main.py

# Single scrape (for testing or cron)
python main.py --once
```

---

## Configuration Settings (`.env`)

| Setting | Default | Change when... |
|---------|---------|-----------------|
| `RAG_LLM_PROVIDER` | `ollama` | You want to use OpenAI (`openai`) or no LLM (`""`) |
| `OLLAMA_MODEL` | `llama3` | You installed a different model |
| `OPENAI_MODEL` | `gpt-4o-mini` | You prefer a different OpenAI model |
| `RAG_TOP_K` | `5` | You want more/fewer results (tune between 3-15) |
| `RAG_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | You want better semantic matching (`all-mpnet-base-v2`) |
| `RAG_CHUNK_SIZE` | `800` | Results are too generic (decrease) or too narrow (increase) |
| `RAG_CHUNK_OVERLAP` | `100` | Rarely needs change; affects context continuity |

**LLM Provider Options:**

```env
# Option 1: Ollama (local, free)
RAG_LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3

# Option 2: OpenAI (API, costs money)
RAG_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# Option 3: Retrieval only (free, no LLM)
RAG_LLM_PROVIDER=
```

---

## Common Issues & Fixes

### "Too many generic results"
**Problem:** Query returns random unrelated bids  
**Try first:**
```bash
# Use metadata filter
python main.py --ask "laptops" --filter product_type=Product

# Or reduce results count in .env:
RAG_TOP_K=3
```

**Try next:**
```env
# Increase semantic weight (meaning > keywords)
# Edit rag/vector_store.py line ~145:
# hybrid_score = (semantic × 0.8) + (keyword × 0.2)  # was 0.6/0.4
```

### "Missing relevant bids"
**Problem:** Query should find results but doesn't  
**Try first:**
```bash
# Search with /search instead (retrieval only)
# In chat: /search laptop bids

# Or increase top_k in .env:
RAG_TOP_K=15
```

**Try next:**
```bash
# Better embedding model
RAG_EMBEDDING_MODEL=all-mpnet-base-v2
# Then reindex:
python main.py --reindex
```

### "Chat exit not working"
**Problem:** `quit` / `bye` doesn't exit  
**Status:** Fixed in current version (exit checked BEFORE query)  
**Supported exit words:** quit, exit, q, bye, goodbye, stop, close, end, done, ok bye

### "/search showing garbled text"
**Problem:** /search output shows PDF raw text instead of item names  
**Status:** Fixed in current version (shows full_item_name from metadata)

### "Slow queries"
**Problem:** Searches take >5 seconds  
**Try:** Decrease `RAG_TOP_K` or `RAG_CHUNK_SIZE` in `.env`

---

## Decision Tree: What Should I Change?

```
Are results too generic?
├─ Yes → reduce RAG_TOP_K to 3
│
Are results missing relevant bids?
├─ Yes → increase RAG_TOP_K to 15
│
Are results wrong types/departments?
├─ Yes → use --filter flag instead
│
Are queries slow?
├─ Yes → decrease RAG_CHUNK_SIZE
│
Do you want different LLM?
├─ Yes → change RAG_LLM_PROVIDER in .env
```

---

## Running Production

### Continuous Loop (Recommended)
```bash
python main.py
# Runs hourly scrapes + auto-indexes bids
# Press Ctrl+C to stop
```

### Systemd Service (Linux)
```bash
sudo systemctl start gem-scraper
sudo systemctl status gem-scraper
sudo systemctl stop gem-scraper
```

### Cron Schedule
```bash
# Every hour
0 * * * * cd /path/to/gem_scraper && python main.py --once

# Every 30 minutes
*/30 * * * * cd /path/to/gem_scraper && python main.py --once

# Daily at 2 AM
0 2 * * * cd /path/to/gem_scraper && python main.py --once
```

---

## Example Queries to Try

```bash
# Simple searches
python main.py --ask "laptop bids"
python main.py --ask "service contracts"
python main.py --ask "Ministry of Defence"

# Complex queries
python main.py --ask "IT equipment bids above 10 lakh from NIC"
python main.py --ask "Which bids are ending this week?"
python main.py --ask "Global tenders in defence or aerospace"

# With filters
python main.py --ask "product bids" --filter product_type=Product
python main.py --ask "services" --filter "bid_type=Service Bid/RAs"
python main.py --ask "maintenance" --filter department=Defence

# In chat mode (/search for quick retrieval without LLM)
python main.py --chat
# Then: /search laptop bids from Intel
# Then: f:product_type=Product server hardware
# Then: quit
```

---

## File Organization

**Input/Output:**
- `storage/gem_bids.db` — SQLite with all bids (auto-created)
- `storage/gem_bids.json` — JSON export for analysis (auto-created)
- `storage/chroma_db/` — Vector embeddings (auto-created)
- `downloads/` — Downloaded PDFs (auto-created)

**Configuration:**
- `.env` — All settings (copy from `.env.example`)
- `config/settings.py` — Loads from .env, exposes to code

**Logs:**
- `logs/scraper.log` — Scraping runs
- `logs/vector_store.log` — RAG operations
- `logs/browser.log` — Browser automation
- Other modules also log

---

## Next Steps

1. **Read [RAG_ARCHITECTURE_GUIDE.md](RAG_ARCHITECTURE_GUIDE.md)** — Deep understanding of system
2. **Read [RAG_SCORING_EXAMPLES.md](RAG_SCORING_EXAMPLES.md)** — Concrete scoring examples
3. **Read [RAG_TUNING_GUIDE.md](RAG_TUNING_GUIDE.md)** — Optimization strategies
4. **Browse [RAG_VISUAL_REFERENCE.md](RAG_VISUAL_REFERENCE.md)** — Diagrams & visuals

---

## FAQ

**Q: Does this cost money?**  
A: Scraping is free. Ollama is free. OpenAI costs ~$0.01 per query.

**Q: Can I use this on Windows?**  
A: Yes, install Tesseract from https://github.com/UB-Mannheim/tesseract/wiki

**Q: How often are bids updated?**  
A: Scraper runs hourly by default. Set `SCRAPE_INTERVAL_MINUTES` in `.env` to change.

**Q: How many bids can it handle?**  
A: Tested up to 10,000 bids. ChromaDB scales to millions.

**Q: Can I query while scraping?**  
A: Yes, SQLite and ChromaDB support concurrent reads.

```
For each bid retrieved:

Semantic Score = 1 - cosine_distance(query_vector, bid_vector)
                 → Captures meaning and intent
                 → Range: 0 to 1

Keyword Score  = Σ(word_matches × field_weights) / total_weights
               → Stop words removed first
               → Returns 0.5 if all words are stop words
               → Range: 0 to 1

Hybrid Score = (Semantic × 0.6) + (Keyword × 0.4)
             → Final ranking score
             → Range: 0 to 1

Higher score = Better match
```

**Visual Example**:
```
Query: "IT Laptops"

Bid A: "Dell Laptops" from IT Dept
  Semantic: 0.88 (embeddings match well)
  Keyword: 0.46 (exact "laptops" match in item name, weight 3.0)
  Hybrid: (0.88 × 0.6) + (0.46 × 0.4) = 0.712 ✓ Top result!

Bid B: "Software Services" from IT Dept
  Semantic: 0.45 (not related to laptops)
  Keyword: 0.20 (only "IT" matches)
  Hybrid: (0.45 × 0.6) + (0.20 × 0.4) = 0.350 ⬇ Lower
```

---

## Quick Command Reference

### Testing & Exploration

```bash
# Interactive chat (best for testing)
python main.py --chat
# Then: type query, or /search query, or quit/bye/done

# Single query
python main.py --ask "IT hardware bids"

# Query with filter
python main.py --ask "bids" --filter product_type=Product

# Retrieval only (no LLM) — shows score breakdown
# Set in .env: RAG_LLM_PROVIDER=
python main.py --ask "laptops"

# System health check
python main.py --stats
```

### Indexing & Maintenance

```bash
# Rebuild entire vector index
python main.py --reindex

# New scrape run (active bids only)
python main.py --once

# Continuous scraping (hourly)
python main.py
# (Ctrl+C to stop)
```

### Chat Mode Commands

| Command | Description |
|---|---|
| `<question>` | Hybrid search + LLM answer |
| `f:<key>=<value> <question>` | Search with metadata filter |
| `/search <question>` | Retrieval only — shows item names + scores |
| `quit` / `bye` / `exit` / `done` | Exit chat (checked before query) |

---

## What's New (Recent Changes)

### Scraper
- **Active bids only**: `browser.select_ongoing_bids()` now called for every bid type — expired/closed bids are automatically skipped
- **Accurate dates**: `get_dates_from_card()` scrapes `start_date` and `end_date` directly from card HTML (not PDF). PDF dates used only as fallback

### Query Engine
- **Exit detection fixed**: `is_exit()` is checked **before** any query processing — typing `quit` or `bye` now exits immediately
- **`/search` fixed**: Shows clean `full_item_name` from metadata, not raw chunk text
- **Wider intent patterns**: More listing/focused keywords detected for smart top_k

### RAG / Scoring
- **Hybrid search**: `_keyword_score()` function with stop word removal and field weights
- **Score breakdown**: Retrieval-only mode shows `Overall Score`, `Semantic (60%)`, `Keyword (40%)` for each result

---

## Decision Tree: What to Change

```
START → Are results good?
  │
  ├─ YES → Use as-is
  │
  └─ NO → What's wrong?
     │
     ├─ Too many irrelevant results?
     │  ├─ Try: RAG_TOP_K = 3 (was 5)
     │  ├─ Try: Semantic weight = 0.7 (was 0.6)
     │  └─ Try: Add filter (--filter product_type=Product)
     │
     ├─ Missing relevant results?
     │  ├─ Try: RAG_TOP_K = 15 (was 5)
     │  ├─ Try: Better model (all-mpnet-base-v2) + reindex
     │  └─ Try: Semantic weight = 0.5 (was 0.6)
     │
     ├─ Wrong department/type?
     │  ├─ Try: Increase type field weight (1.0 → 3.0)
     │  └─ Try: Add filter (--filter department=IT)
     │
     ├─ Too slow?
     │  ├─ Try: RAG_LLM_PROVIDER = "" (no LLM)
     │  ├─ Try: Smaller chunks (RAG_CHUNK_SIZE = 400)
     │  └─ Try: Fewer results (RAG_TOP_K = 3)
     │
     └─ Duplicates in results?
        └─ Try: python main.py --reindex
```

---

## Configuration Quick Reference

### In `.env` file:

```env
# Retrieval settings
RAG_TOP_K=5
RAG_CHUNK_SIZE=800
RAG_CHUNK_OVERLAP=100

# Embedding model
RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2
# Options:
#   all-MiniLM-L6-v2  (fast, good — default)
#   all-mpnet-base-v2 (accurate, slow — requires reindex)
#   all-MiniLM-L12-v2 (good balance)

# LLM Provider
RAG_LLM_PROVIDER=ollama
# Options:
#   ollama  (local, free)
#   openai  (cloud, paid)
#   ""      (retrieval only — shows score breakdown)

# Ollama settings
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# OpenAI settings
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

### In code files:

**File: `rag/vector_store.py` — search function**
```python
# Adjust hybrid weights:
hybrid_score = (semantic_score * 0.6) + (keyword_score * 0.4)
#                                  ↑                    ↑
#                    Change these values to tune behavior
```

**File: `rag/vector_store.py` — `_keyword_score` function**
```python
# Adjust field weights:
fields_text = {
    "full_item_name": 3.0,    # Item name match importance
    "department": 1.5,        # Department match importance
    "bid_type": 1.0,          # Bid type match importance
    "product_type": 1.0,      # Product type match importance
}
```

---

## Common Tuning Profiles

### Profile 1: **High Precision** (Exact matches)
```env
RAG_TOP_K=3
RAG_CHUNK_SIZE=600
RAG_LLM_PROVIDER=
```
```python
hybrid_score = (semantic_score * 0.7) + (keyword_score * 0.3)
fields_text["full_item_name"] = 5.0
```

### Profile 2: **High Recall** (Find everything related)
```env
RAG_TOP_K=20
RAG_CHUNK_SIZE=1500
RAG_EMBEDDING_MODEL=all-mpnet-base-v2
RAG_LLM_PROVIDER=ollama
```
```python
hybrid_score = (semantic_score * 0.8) + (keyword_score * 0.2)
fields_text["full_item_name"] = 2.0
```

### Profile 3: **Balanced** (Default)
```env
RAG_TOP_K=5
RAG_CHUNK_SIZE=800
RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2
RAG_LLM_PROVIDER=ollama
```
```python
hybrid_score = (semantic_score * 0.6) + (keyword_score * 0.4)
# fields_text = default
```

### Profile 4: **Maximum Speed** (API serving)
```env
RAG_TOP_K=3
RAG_CHUNK_SIZE=400
RAG_LLM_PROVIDER=
```
```python
hybrid_score = (semantic_score * 0.7) + (keyword_score * 0.3)
fields_text["full_item_name"] = 4.0
```

---

## Troubleshooting Matrix

| Problem | First Check | Solution 1 | Solution 2 |
|---------|-------------|-----------|-----------|
| Results too broad | RAG_TOP_K value | Lower to 2-3 | Increase semantic weight |
| Results too narrow | Query wording | Broaden query | Increase top_k to 10-15 |
| Wrong type/dept | Keyword scores | Boost field weight | Add explicit filter |
| Too slow | Where's time? | Remove LLM | Smaller chunks |
| No results | Vector store status | python --stats | python --reindex |
| Duplicates | Index health | python --reindex | Check database |
| Exit not working | query_engine.py | is_exit() before query | Update code |
| /search garbled | query_engine.py | search_only() enriches item name | Update code |
| Wrong dates | Card HTML | get_dates_from_card() | Check portal card format |

---

## Configuration Cheat Sheet

### Changes that require REINDEX:
- ✓ RAG_EMBEDDING_MODEL
- ✓ RAG_CHUNK_SIZE
- ✓ RAG_CHUNK_OVERLAP

### Changes that don't require reindex:
- RAG_TOP_K
- Hybrid weights (0.6 / 0.4)
- Field weights (full_item_name, department, etc.)
- RAG_LLM_PROVIDER
- LLM model name

### After changing requires-reindex settings:
```bash
python main.py --reindex
```

---

## Performance Expectations

### Indexing
```
Operation: python main.py --reindex

Typical times:
- 100 bids:   10-20 seconds
- 1000 bids:  2-3 minutes
- 10000 bids: 20-30 minutes
```

### Querying
```
Operation: python main.py --ask "query"

Typical times:
- Embedding query: 50ms
- Search:          100-500ms
- LLM:             1000-3000ms (most time!)

To speed up: RAG_LLM_PROVIDER="" → 150-550ms total
```

---

## Important Files to Know

```
gem_scraper/
├── main.py                    ← Entry point (all commands)
├── MINERU_MARKDOWN_PASER.py   ← Mineru & Docling PDF parser script
├── sync_to_github.sh          ← GitHub sync automation script
├── config/settings.py         ← All config values
├── rag/
│  ├── query_engine.py         ← Exit detection + smart top_k
│  ├── vector_store.py         ← HYBRID SCORING + _keyword_score
│  ├── embedder.py             ← Embedding & chunking
│  └── llm.py                  ← LLM + score breakdown display
├── core/
│  ├── parser.py               ← PDF parsing + get_dates_from_card
│  └── browser.py              ← Playwright + select_ongoing_bids
├── pipeline/
│  ├── scraper.py              ← Active bids only scrape run
│  └── scheduler.py            ← Hourly loop + new bid alerts
├── storage/
│  ├── database.py             ← SQLite + auto RAG index
│  └── gem_bids.db             ← Your bids database
├── STANDLONE TEST SCRIPTS/    ← Isolated scraper test & evaluation scripts
└── Documentation/
   ├── README.md               ← Main overview
   └── Mineru_README.md        ← Mineru VLM & document conversion documentation
```

---

## Summary

Your RAG system is:
1. **Active-bids focused**: Only scrapes ongoing/open bids via portal filter
2. **Date-accurate**: Dates from card HTML, not unreliable PDF fields
3. **Well-architected**: Separates concerns (scrape → embed → search → answer)
4. **Tunable**: Multiple parameters to optimize for your needs
5. **Transparent**: Score breakdown shows semantic + keyword components
6. **Exit-safe**: Chat mode exits cleanly on quit/bye/done

The scoring formula is the heart of it all:
```
Hybrid Score = (Semantic × 0.6) + (Keyword × 0.4)
```
