# GeM Bid RAG System — Quick Start Summary

> Complete documentation overview  
> **Last Updated**: May 2026

---

## System at a Glance

```
Your system = Semantic Search + Keyword Matching + Optional LLM

Data Flow:
  Scrape PDFs (active bids only) → Extract fields + card dates
       → Store in SQLite + Vector DB
                    ↓
  User Query → Exit Check → Smart top_k → Embed
       → Hybrid Search → Format results → Show/LLM
```

### Key Numbers

| Parameter | Current | Impact |
|-----------|---------|--------|
| RAG_TOP_K | 5 | Results returned per query |
| RAG_CHUNK_SIZE | 800 | Characters per chunk |
| RAG_CHUNK_OVERLAP | 100 | Overlap for context |
| Semantic weight | 0.6 | 60% of final score |
| Keyword weight | 0.4 | 40% of final score |

---

## The Scoring Formula (Most Important)

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
GeM Tender/
├── main.py                    ← Entry point (all commands)
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
└── storage/
   ├── database.py             ← SQLite + auto RAG index
   └── gem_bids.db             ← Your bids database
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
