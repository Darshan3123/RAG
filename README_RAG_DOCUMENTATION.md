# GeM Bid RAG Documentation — Master Index

> Complete RAG system understanding & tuning guides  
> **Last Updated**: May 2026

---

## What You Have

5 comprehensive documentation files covering:

- **How the RAG works** (architecture, data flow, components)
- **How scoring is calculated** (hybrid scoring formula with examples)
- **How to tune it** (configuration, optimization strategies)
- **Visual references** (diagrams, decision trees, comparison matrices)
- **Quick start** (commands, configurations, troubleshooting)

---

## Documentation Files

### 1. RAG_QUICK_START.md — START HERE
**Best for**: First time users, quick answers  
**Contains**:
- What's new (recent code changes)
- Quick command reference
- Key scoring formula
- Common configurations
- Decision tree for problems
- Troubleshooting matrix

---

### 2. RAG_ARCHITECTURE_GUIDE.md — DEEP DIVE
**Best for**: Understanding the system completely  
**Contains**:
- System overview with diagrams
- Complete data flow (scraping → indexing → querying)
- Active-bids-only scraping via `select_ongoing_bids()`
- Card-based date extraction via `get_dates_from_card()`
- Component-by-component explanation
- Hybrid scoring theory (semantic + keyword)
- All configuration parameters explained
- Performance optimization section

---

### 3. RAG_SCORING_EXAMPLES.md — VISUAL LEARNING
**Best for**: Understanding scoring through examples  
**Contains**:
- Step-by-step scoring calculations
- 3 detailed examples with real numbers
- Stop word removal in `_keyword_score()`
- Field weight impact analysis
- Score distribution patterns
- Score breakdown in retrieval-only mode
- Formula reference sheet

---

### 4. RAG_TUNING_GUIDE.md — PRACTICAL OPTIMIZATION
**Best for**: Actually tuning the system  
**Contains**:
- 9 scenario-based solutions including:
  - Results too generic
  - Missing relevant results
  - Wrong types/departments
  - Slow queries
  - LLM hallucination
  - Duplicates
  - Exit not working in chat (fixed)
  - /search showing garbled text (fixed)
- 4 configuration templates
- Testing protocol
- Advanced intent detection
- Debugging commands

---

### 5. RAG_VISUAL_REFERENCE.md — DIAGRAMS & CHARTS
**Best for**: Visual learners, quick reference  
**Contains**:
- System architecture flowchart
- Scraper pipeline (active bids + card dates)
- Scoring components breakdown
- Data flow (all 4 stages)
- Embedding model comparison table
- Query intent detection visual
- Performance tuning map
- Index health monitoring
- Parameter impact matrix
- Help decision tree
- File organization

---

## Key Concepts At A Glance

### The Scoring Formula

```
Hybrid Score = (Semantic Score × 0.6) + (Keyword Score × 0.4)

Semantic Score  = 1 - cosine_distance(query_vector, chunk_vector)
                  Captures: Meaning, Intent, Concepts

Keyword Score   = Σ(word_matches × field_weights) / total_weights
                  Stop words removed first
                  Returns 0.5 if all words are stop words
                  Captures: Exact matches in structured fields

Result: 0.0 (completely irrelevant) to 1.0 (perfect match)
```

### Recent Code Changes

| Change | File | What it does |
|--------|------|-------------|
| `select_ongoing_bids()` | `core/browser.py` | Filters active bids only on GeM portal |
| `get_dates_from_card()` | `core/parser.py` | Scrapes dates from card HTML (accurate) |
| `_to_24h()` | `core/parser.py` | Converts AM/PM time to 24-hour format |
| `_keyword_score()` | `rag/vector_store.py` | TF-IDF style keyword matching with stop words |
| Hybrid search | `rag/vector_store.py` | 60% semantic + 40% keyword scoring |
| Score breakdown | `rag/llm.py` | Shows semantic + keyword components in output |
| `is_exit()` first | `rag/query_engine.py` | Exit checked before query (chat fix) |
| `search_only()` enriched | `rag/query_engine.py` | `/search` shows item name, not chunk text |
| Wider intent patterns | `rag/query_engine.py` | More keywords for smart top_k detection |

### Three Ways to Improve Results

1. **Change Weights** (no reindex needed)
   - Adjust hybrid score: `0.6/0.4 → 0.7/0.3`
   - Adjust field weights: `full_item_name 3.0 → 5.0`

2. **Change Search Strategy** (no reindex needed)
   - Adjust top_k: `5 → 3` (precision) or `15` (recall)
   - Use filters: `--filter product_type=Product`

3. **Change Indexing** (REQUIRES reindex)
   - Embedding model: `MiniLM → mpnet`
   - Chunk size: `800 → 1500`
   - Command: `python main.py --reindex`

---

## Quick Start (30 seconds)

```bash
# 1. Try the chat interface
python main.py --chat

# 2. Type: "IT department laptops"
# 3. See results with scores
# 4. Try: /search laptops  (retrieval only, shows item names)
# 5. Type: quit
```

---

## Common Questions

**Q: How do I make results more relevant?**  
A: Read → RAG_TUNING_GUIDE.md → Scenario 1

**Q: How does the scoring work?**  
A: Read → RAG_SCORING_EXAMPLES.md → Example 1

**Q: What should I change first?**  
A: Follow → RAG_QUICK_START.md → Decision Tree

**Q: Why are dates sometimes wrong?**  
A: Dates now come from card HTML (`get_dates_from_card`), not PDF. PDF dates used only as fallback.

**Q: Why does the scraper only get active bids?**  
A: `browser.select_ongoing_bids()` clicks the "Ongoing Bids/RA" filter on the portal before scraping each bid type.

**Q: Why are results duplicated?**  
A: Try `python main.py --reindex`

**Q: How do I see the score breakdown?**  
A: Set `RAG_LLM_PROVIDER=` in `.env` (retrieval-only mode shows semantic + keyword scores)

**Q: Should I use Ollama or OpenAI?**  
A: See → RAG_ARCHITECTURE_GUIDE.md → LLM Integration section

---

## Codebase Structure

```
main.py                  ← Run commands here
config/settings.py       ← Configure everything
core/
  ├── browser.py         ← Playwright + select_ongoing_bids()
  └── parser.py          ← PDF + get_dates_from_card()
pipeline/
  ├── scraper.py         ← Active bids only scrape run
  └── scheduler.py       ← Hourly loop + new bid alerts
rag/
  ├── embedder.py        ← Embedding & chunking
  ├── vector_store.py    ← Hybrid scoring + _keyword_score()
  ├── query_engine.py    ← Exit detection + smart top_k
  └── llm.py             ← LLM + score breakdown
storage/
  ├── database.py        ← SQLite + auto RAG index
  └── gem_bids.db        ← Your bids
```

---

## Learning Paths

### "I just want it to work"
1. RAG_QUICK_START.md (5 min)
2. `python main.py --chat` (2 min)
3. Done!

### "I want to understand everything"
1. RAG_ARCHITECTURE_GUIDE.md (20 min)
2. RAG_SCORING_EXAMPLES.md (15 min)
3. RAG_VISUAL_REFERENCE.md (10 min)

### "I want to optimize results"
1. RAG_QUICK_START.md → Decision Tree (2 min)
2. RAG_TUNING_GUIDE.md → Your scenario (10 min)
3. Make changes and test

### "Something's broken"
1. RAG_QUICK_START.md → Troubleshooting Matrix (1 min)
2. RAG_VISUAL_REFERENCE.md → Help Decision Tree if needed
