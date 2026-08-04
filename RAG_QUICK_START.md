# GeM Bid RAG System — Quick Start Guide

> **Last Updated:** August 2026  
> **For:** First-time users, quick answers, command reference  
> See [README_RAG_DOCUMENTATION.md](README_RAG_DOCUMENTATION.md) for complete guide index

---

## What This System Does

1. **Scrapes GeM Portal** — Active bids only (via "Ongoing Bids/RA" filter)
2. **Extracts Bid Data & Links** — Mineru VLM PDF-to-Markdown + PyMuPDF hyperlink extraction + 24h card HTML dates
3. **Builds Hybrid Vector Database** — ChromaDB (BGE dense embeddings) + BM25Okapi (sparse keyword index)
4. **Answers Questions** — Hybrid RAG search (BGE + BM25 + RRF + BGE CrossEncoder reranking) + optional LLM

---

## System At A Glance

```
PIPELINE:
  Scrape (active bids) → Mineru VLM conversion + Card dates → Store SQLite + ChromaDB
                              ↓
  Query → Embed (BGE) → Dense + Sparse (BM25) → RRF → CrossEncoder Rerank → LLM answer
```

### Key Numbers (Defaults)

| Parameter | Value | Impact |
|-----------|-------|--------|
| `RAG_TOP_K` | 5 | Unique bids returned per query |
| `RAG_FETCH_K` | 40 | Over-fetched candidates per retrieval leg before reranking |
| `RAG_CHUNK_SIZE` | 800 | Characters per text chunk |
| `RAG_CHUNK_OVERLAP` | 100 | Overlap for context continuity |
| `RAG_EMBEDDING_MODEL` | `BAAI/bge-base-en-v1.5` | High-accuracy dense vector encoder (local offline mode) |
| `RAG_RERANKER_MODEL` | `BAAI/bge-reranker-base` | Cross-Encoder precision reranker with Sigmoid logit conversion |
| Reranker weight | 0.60 | 60% of final weighted score |
| Dense weight | 0.25 | 25% of final weighted score |
| BM25 weight | 0.15 | 15% of final weighted score |
| Relative cutoff | 70% | Candidates scoring < 70% of top match are filtered out |

---

## The Scoring Formula (MOST IMPORTANT)

This is the heart of RAG relevance:

```
For each user query:

┌─────────────────────────────────────────────────────────┐
│ DENSE RETRIEVAL (BGE Embedder)                          │
│ ─────────────────────────────────────────────────────── │
│ 1. Embed query with BGE prompt instruction prefix       │
│ 2. Compute cosine similarity against chunk vectors      │
│ 3. semantic_score = 1 - distance (0 to 1)               │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│ SPARSE RETRIEVAL (BM25Okapi Index)                      │
│ ─────────────────────────────────────────────────────── │
│ 1. Tokenize query & search against metadata-enriched    │
│    corpus (item name, department, bid no, body text)    │
│ 2. bm25_score = min(1.0, score / 20.0)                  │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│ RECIPROCAL RANK FUSION (RRF) & DEDUPLICATION            │
│ ─────────────────────────────────────────────────────── │
│ Combine dense + sparse rankings: rrf = Σ 1 / (60 + rank)│
│ Keep best chunk per unique Bid No                       │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│ CROSS-ENCODER RERANKER (BAAI/bge-reranker-base)         │
│ ─────────────────────────────────────────────────────── │
│ Score (query, chunk_doc) pairs using CrossEncoder       │
│ rerank_score = Sigmoid(logit) (0 to 1)                  │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│ WEIGHTED FINAL SCORE & RELATIVE CUTOFF FILTERING        │
│ ─────────────────────────────────────────────────────── │
│ Final = (rerank_score × 0.6)                            │
│       + (semantic_score × 0.25)                         │
│       + (bm25_score × 0.15)                             │
│                                                         │
│ Cutoff: Drop candidates scoring < 70% of top result      │
└─────────────────────────────────────────────────────────┘
```

**Real Example:**
```
Query: "Dell Laptop bids"

Bid A: "Dell Laptops 15-inch from Tech Ministry" [exact item match]
  ├─ Dense score:   0.92 (excellent semantic match)
  ├─ BM25 score:    0.95 (exact keywords match in metadata card)
  ├─ Rerank score:  0.98 (high CrossEncoder confidence)
  └─ Final Score:  (0.98 × 0.6) + (0.92 × 0.25) + (0.95 × 0.15) = 0.9605 ✓ TOP

Bid B: "Office Furniture from Tech Ministry"
  ├─ Dense score:   0.35 (weak, about furniture)
  ├─ BM25 score:    0.10 (only "Ministry" matches)
  ├─ Rerank score:  0.02 (very low CrossEncoder relevance)
  └─ Final Score:  (0.02 × 0.6) + (0.35 × 0.25) + (0.10 × 0.15) = 0.1145 ⬇ Filtered out by 70% relative threshold
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

# Query with metadata filter
python main.py --ask "laptops" --filter product_type=Product

# Search specific single Bid Number on GeM portal
python main.py --bid "GEM/2026/B/7768206"

# View system health & database stats
python main.py --stats

# Re-index SQLite database records into ChromaDB
python main.py --reindex

# Clean reset of SQLite DB, JSON exports, and vector store
python main.py --reset
```

### Scraping Modes

```bash
# Production continuous scrape loop (runs hourly)
python main.py

# Single scrape run (scrapes all 9 categories once and exits)
python main.py --once
```

---

## Configuration Settings (`.env`)

| Setting | Default | Description |
|---------|---------|-------------|
| `RAG_LLM_PROVIDER` | `ollama` | Choice: `ollama`, `openai`, or `""` (retrieval-only mode) |
| `OLLAMA_MODEL` | `llama3` | Ollama model identifier |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI API model identifier |
| `RAG_TOP_K` | `5` | Unique bids returned per query (tune between 3-15) |
| `RAG_FETCH_K` | `40` | Over-fetched candidates per retrieval leg before reranking |
| `RAG_EMBEDDING_MODEL` | `BAAI/bge-base-en-v1.5` | Dense vector encoder model |
| `RAG_RERANKER_MODEL` | `BAAI/bge-reranker-base` | Cross-Encoder reranker model |
| `RAG_CHUNK_SIZE` | `800` | Characters per text chunk |
| `RAG_CHUNK_OVERLAP` | `100` | Overlap for context continuity |

---

## Common Issues & Fixes

### "Too many generic results"
**Problem:** Query returns random unrelated bids  
**Fix:**
- Use metadata filter: `python main.py --ask "laptops" --filter product_type=Product`
- Relative cutoff threshold (70% top score) in `rag/vector_store.py` automatically drops noise matches.

### "Missing relevant bids"
**Problem:** Query should find results but doesn't  
**Fix:**
- Use `/search` command in chat mode to view raw search scores.
- Increase `RAG_TOP_K` in `.env` (e.g. `RAG_TOP_K=15`).

### "Chat exit not working"
**Status:** Fixed in current version (exit checked BEFORE query processing).  
**Supported exit words:** `quit`, `exit`, `q`, `bye`, `goodbye`, `stop`, `close`, `end`, `done`, `ok bye`.

### "/search showing garbled text"
**Status:** Fixed in current version (shows `full_item_name` from metadata, end date, and score).

---

## Output Artifact Storage (`downloads/<safe_bid_no>/`)

Every scraped bid is saved in a dedicated subfolder `downloads/<safe_bid_no>/` containing 4 output files:
1. `<safe_bid_no>.html`: Raw HTML card snippet.
2. `<safe_bid_no>.pdf`: Downloaded Bid PDF (and optional `_RA.pdf`).
3. `<safe_bid_no>.md`: Mineru VLM converted Markdown (with PyMuPDF extracted hyperlinks).
4. `<safe_bid_no>.json`: Unified JSON schema artifact.
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
