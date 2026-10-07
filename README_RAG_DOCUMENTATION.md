# GeM Bid RAG System — Documentation Master Index

> **Complete RAG system understanding & tuning guides**  
> **Last Updated:** August 2026  
> **Project Status:** Production-ready with Mineru VLM, PyMuPDF hyperlink extraction, BGE + BM25 + RRF + CrossEncoder reranking

---

## 📋 What You Have

A complete set of RAG system documentation covering:

- ✅ **How the RAG works** (architecture, all data flows, components)
- ✅ **How scoring is calculated** (BGE dense + BM25 + RRF + CrossEncoder reranker formula with real examples)
- ✅ **How to tune it** (configuration strategies for your use case)
- ✅ **Visual references** (diagrams, flowcharts, decision trees)
- ✅ **Quick commands** (CLI reference, troubleshooting, examples)
- ✅ **Mineru & VLM Engine integration** ([Mineru_README.md](Mineru_README.md))

---

## 📚 Document Index

### 1️⃣ [RAG_QUICK_START.md](RAG_QUICK_START.md) — **START HERE**

**Best for:** New users, quick answers, troubleshooting  
**Read time:** 5-10 minutes

**Contains:**
- What the system does (scraping + Mineru VLM + hybrid RAG + answering)
- The BGE + BM25 + CrossEncoder reranker scoring formula with visual example
- All CLI commands (--ask, --chat, --stats, --reindex, --once, --bid)
- Configuration parameters & when to change them
- Common issues & quick fixes (too generic results, missing results, slow queries)
- Decision tree for "what should I change?"
- Example queries to try
- FAQ

**Key Takeaway:** Run `python main.py --chat` to start experimenting

---

### 2️⃣ [RAG_ARCHITECTURE_GUIDE.md](RAG_ARCHITECTURE_GUIDE.md) — **DEEP DIVE**

**Best for:** Engineers, architects, understanding the complete system  
**Read time:** 20-30 minutes

**Contains:**
- System overview (all components shown in diagrams)
- **Complete data flow** (6 steps: scraping → Mineru VLM parsing → PyMuPDF hyperlink extraction → storage → hybrid indexing → querying → output)
- **Scraper details:**
  - "Active Bids Only" filter via `select_ongoing_bids()` (no expired bids)
  - Card-based 24h date extraction (`get_dates_from_card()`)
  - 9 bid types scraped
  - Anti-bot measures (delays, UA rotation, stealth JS)
- **Parser details:**
  - Mineru VLM PDF document conversion in Zero Save Mode with vLLM acceleration
  - PyMuPDF (`fitz`) hyperlink extraction (`utils/pdf_hyperlinks.py`)
  - 10-section structured Markdown parser in `core/parser.py` (`parse_bid_data()`)
  - Merged table cell grid expansion (`_expand_table_grid()`)
- **Database schema** (bids table + run_log table)
- **Embeddings:**
  - `BAAI/bge-base-en-v1.5` model (local offline mode with BGE query instruction prefixing)
  - Chunking strategy (800 chars, 100 overlap + metadata card chunk 0)
- **Vector Store (ChromaDB):**
  - Upsert process and chunk management
  - Cosine similarity HNSW search algorithm
- **Hybrid Search & Reranking in depth:**
  - Dense retrieval (BGE embeddings)
  - Sparse retrieval (BM25Okapi keyword search)
  - Reciprocal Rank Fusion (RRF)
  - Cross-Encoder Reranking (`BAAI/bge-reranker-base` with Sigmoid logit conversion)
  - Weighted Score: `(Reranker × 0.6) + (Dense × 0.25) + (BM25 × 0.15)`
  - Relative score cutoff filtering (70% top-score threshold)
- **Query processing:**
  - Exit detection (quit/bye/done)
  - Smart top_k adjustment by intent
  - Vector search pipeline
  - LLM integration (Ollama / OpenAI / Retrieval-only mode)
  - Score breakdown generation
- **All configuration parameters explained**
- **Performance optimization section**
- **Troubleshooting guide**

**Key Takeaway:** Understand every component and why it exists

---

### 3️⃣ [RAG_SCORING_EXAMPLES.md](RAG_SCORING_EXAMPLES.md) — **VISUAL LEARNING**

**Best for:** Understanding scoring through worked examples  
**Read time:** 10-15 minutes

**Contains:**
- **3 complete scoring walkthroughs** with real numbers
- Example 1: "Laptop bids" query
- Example 2: "IT Department Services"
- Example 3: "Complex multi-word query"
- Step-by-step calculation breakdown:
  - BGE query instruction prefixing & embedding generation
  - Dense cosine similarity score calculation
  - BM25Okapi sparse keyword score calculation
  - Reciprocal Rank Fusion (RRF) combination
  - BAAI/bge-reranker-base Cross-Encoder Sigmoid logit scoring
  - Final weighted ranking and relative 70% cutoff filtering
- Score breakdown in retrieval-only mode
- Formula reference sheet

**Key Takeaway:** See exactly how each score is calculated with real examples

---

### 4️⃣ [RAG_TUNING_GUIDE.md](RAG_TUNING_GUIDE.md) — **PRACTICAL OPTIMIZATION**

**Best for:** Actually improving RAG performance for your use case  
**Read time:** 15-20 minutes

**Contains:**
- **9 real-world scenarios:**
  1. Results too generic → adjust top_k or relative cutoff threshold
  2. Missing relevant results → increase recall or disable reranker
  3. Wrong bid types in results → use metadata filters (`f:key=value`)
  4. Slow queries → GPU memory tuning for vLLM & PyTorch
  5. LLM hallucinating → zero-hallucination prompt & retrieval-only mode
  6. Duplicate results → bid deduplication logic
  7. Exit not working in chat → checked before query
  8. /search showing garbled text → clean item name extraction
  9. Custom intent detection → smart top_k rules
- **For each scenario:**
  - Problem description & root cause
  - Solutions in order of impact
  - Code changes needed & configuration templates
- **4 complete tuning templates:**
  - Precision mode (high accuracy, fewer results)
  - Recall mode (more results, broader coverage)
  - Balanced mode (default settings)
  - Production mode (optimized GPU / offline deployment)
- **Testing protocol** (how to measure improvement)
- **Advanced topics:**
  - Embedding model & reranker comparison
  - Chunk size impact & metadata card strategy
  - RRF & Cross-Encoder weighting tuning

**Key Takeaway:** Know exactly which settings to change for your specific problem

---

### 5️⃣ [RAG_VISUAL_REFERENCE.md](RAG_VISUAL_REFERENCE.md) — **DIAGRAMS & CHARTS**

**Best for:** Visual learners, quick reference during troubleshooting  
**Read time:** 10 minutes (reference, not sequential)

**Contains:**
- **System architecture flowchart** (all components + data flow)
- **Scraper & Mineru VLM pipeline diagram:**
  - Filter selection & active bids only filter
  - Card 24h date extraction
  - PDF download, PyMuPDF hyperlink extraction, and Mineru VLM conversion
  - Per-bid artifact storage in `downloads/<safe_bid_no>/`
- **Hybrid Scoring breakdown:**
  - Dense track (BGE embeddings)
  - Sparse track (BM25Okapi keyword search)
  - RRF fusion
  - Cross-Encoder reranker with Sigmoid logit conversion
- **Complete data flow** (colored stages)
- **Embedding model & reranker comparison table**
- **Query intent detection visual**
- **Parameter impact matrix**
- **Help decision tree**

**Key Takeaway:** Visual quick reference for concepts and troubleshooting

---

## 🗺️ How to Use This Documentation

### I'm new, where do I start?
1. Read [RAG_QUICK_START.md](RAG_QUICK_START.md) (10 min)
2. Run `python main.py --chat` (5 min)
3. Try example queries (5 min)
4. **Done!** You're ready to use the system

### I want to understand the system completely
1. Start with [RAG_QUICK_START.md](RAG_QUICK_START.md) (quick overview)
2. Read [RAG_ARCHITECTURE_GUIDE.md](RAG_ARCHITECTURE_GUIDE.md) (complete details)
3. Review [RAG_VISUAL_REFERENCE.md](RAG_VISUAL_REFERENCE.md) (diagrams for clarity)
4. **Bonus:** Read [RAG_SCORING_EXAMPLES.md](RAG_SCORING_EXAMPLES.md) (deep examples)

### Results aren't good, how do I improve?
1. Check [RAG_QUICK_START.md#Decision Tree](RAG_QUICK_START.md) (find your problem)
2. Read relevant section in [RAG_TUNING_GUIDE.md](RAG_TUNING_GUIDE.md) (get solutions)
3. Try the suggested changes (incremental, one at a time)
4. Test and measure improvement
5. Read [RAG_VISUAL_REFERENCE.md](RAG_VISUAL_REFERENCE.md#Parameter Impact Matrix) (understand side effects)

### I want to optimize for production
1. Read [RAG_TUNING_GUIDE.md](RAG_TUNING_GUIDE.md#Full tuning config for "production" mode) (production template)
2. Read [RAG_ARCHITECTURE_GUIDE.md#Performance](RAG_ARCHITECTURE_GUIDE.md) (scaling considerations)
3. Review [RAG_QUICK_START.md#Running Production](RAG_QUICK_START.md) (deployment options)

---

## 🎯 Key Concepts At A Glance

### The Scoring Formula
```
Final Score = (Semantic × 0.6) + (Keyword × 0.4)

Semantic: How well meanings match (0-1)
Keyword:  How many exact words match (0-1)
Range:    0 (no match) to 1 (perfect match)
```

### Active Bids Only
```
Scraper applies "Ongoing Bids/RA" filter
→ Only OPEN bids are scraped
→ Expired/closed bids are skipped automatically
```

### Card-Based Dates
```
Dates scraped from HTML cards (accurate)
PDF dates used only as fallback
Card format: "DD-MM-YYYY HH:MM AM/PM"
Stored as: "DD-MM-YYYY HH:MM:SS"
```

### Smart Top_K
```
Query: "show all bids" → top_k=15 (more results)
Query: "find bid GEM/123" → top_k=2 (focused)
Query: "laptop bids" → top_k=5 (default)
```

---

## 📊 Document Cross-Reference

| Question | Document | Section |
|----------|----------|---------|
| How do I use the system? | QUICK_START | Quick Command Reference |
| What is the scoring formula? | QUICK_START or SCORING_EXAMPLES | The Scoring Formula |
| How does the scraper work? | ARCHITECTURE | Component Architecture #1 |
| How are dates extracted? | ARCHITECTURE | Phase 1: Complete Data Flow, Step 3 |
| How does hybrid search work? | SCORING_EXAMPLES or ARCHITECTURE | Hybrid Scoring sections |
| Results too generic | TUNING_GUIDE | Scenario 1 |
| Missing relevant results | TUNING_GUIDE | Scenario 2 |
| System is slow | TUNING_GUIDE or QUICK_START | Scenario 4 or Common Issues |
| Show me all components | VISUAL_REFERENCE | System Architecture Flowchart |
| How do I improve results? | QUICK_START | Decision Tree |

---

## 🔄 Recent Fixes (May 2026)

1. ✅ **Exit detection fixed** — Exit words checked BEFORE query processing
2. ✅ **'/search' display fixed** — Shows full_item_name from metadata, not raw chunks
3. ✅ **Card date extraction** — Accurate dates from HTML, PDF as fallback
4. ✅ **Active bids filter** — "Ongoing Bids/RA" filter applied automatically

---

## 📞 Quick Help

Need specific information? Jump to:

- **Commands:** [QUICK_START#Quick Command Reference](RAG_QUICK_START.md)
- **Configuration:** [QUICK_START#Configuration Settings](RAG_QUICK_START.md)
- **Scoring math:** [SCORING_EXAMPLES.md](RAG_SCORING_EXAMPLES.md)
- **System design:** [ARCHITECTURE_GUIDE.md](RAG_ARCHITECTURE_GUIDE.md)
- **Improvement strategies:** [TUNING_GUIDE.md](RAG_TUNING_GUIDE.md)
- **Visual aids:** [VISUAL_REFERENCE.md](RAG_VISUAL_REFERENCE.md)

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
main.py                             ← Main entry point (all commands)
MINERU_MARKDOWN_PASER.py             ← Mineru & Docling PDF parser script
sync_to_github.sh                    ← GitHub sync automation script
config/settings.py                  ← Configure settings & environment
core/
  ├── browser.py                    ← Playwright + select_ongoing_bids()
  └── parser.py                     ← PDF text extraction + card dates
pipeline/
  ├── scraper.py                    ← Active bids scraper run
  └── scheduler.py                  ← Hourly background loop
rag/
  ├── embedder.py                   ← Chunking & sentence-transformer embeddings
  ├── vector_store.py               ← Hybrid scoring + keyword matching
  ├── query_engine.py               ← Exit detection + smart top_k
  └── llm.py                        ← LLM answer generation / score breakdown
storage/
  ├── database.py                   ← SQLite DB & auto-indexing
  └── gem_bids.db                   ← SQLite database file
STANDLONE TEST SCRIPTS/             ← Isolated scraper testing & evaluation scripts
  ├── TEST_STANDALONE_SCRAPPER.py
  ├── TEST_STANDALONE_SCRAPPER_MULTI_ITEM_ONLY.py
  ├── TEST_STANDALONE_SCRAPPER_SCRAPE_PARTICULAR_BID.py
  └── TEST_STANDALONE_SCRAPPER_WITH_EVAL_METHODS_SPLIT_REPORT.py
Documentation/
  ├── README.md                     ← Main overview
  ├── Mineru_README.md              ← Mineru document conversion guide
  ├── RAG_QUICK_START.md             ← Quick reference
  ├── RAG_ARCHITECTURE_GUIDE.md      ← Deep dive architecture
  ├── RAG_SCORING_EXAMPLES.md        ← Scoring walkthroughs
  ├── RAG_TUNING_GUIDE.md            ← Optimization guide
  ├── RAG_VISUAL_REFERENCE.md        ← Visual diagrams
  └── README_RAG_DOCUMENTATION.md    ← Master documentation index
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
