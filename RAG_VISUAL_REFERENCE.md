# RAG System — Visual Reference & Architecture Diagrams

> Quick visual guides for understanding the system  
> **Last Updated**: May 29, 2026

---

## System Architecture (Top Level)

```
┌────────────────────────────────────────────────────────────────┐
│                    YOUR RAG SYSTEM                              │
├────────────────────────────────────────────────────────────────┤
│                                                                  │
│  INPUT              PROCESSING              STORAGE             │
│  ────────           ──────────              ───────             │
│                                                                  │
│  GeM           ┌─────────────┐                                  │
│  Website ────→ │  Scraper    │────┐                            │
│                │ (browser.py) │   │                            │
│                └─────────────┘    │                            │
│                                   ▼                            │
│                          ┌─────────────┐                       │
│                          │  Parser     │────┐                  │
│                          │(parser.py)  │    │                  │
│                          └─────────────┘    │                  │
│                                             ▼                  │
│                           PDF → SQLite ← New Bids             │
│                           Text   DB       (database.py)       │
│                            ↓                                   │
│                    ┌─────────────────┐                        │
│                    │ RAG Indexing    │                        │
│                    │ (embedder.py)   │                        │
│                    └────────┬────────┘                        │
│                             │                                  │
│          ┌──────────────────┼──────────────────┐               │
│          ▼                  ▼                  ▼               │
│    ┌──────────┐      ┌────────────┐    ┌────────────┐        │
│    │ Chunks   │      │ Embeddings │    │  Metadata  │        │
│    │ (Text)   │      │ (Vectors)  │    │ (Fields)   │        │
│    └────┬─────┘      └──────┬─────┘    └──────┬─────┘        │
│         │                   │                  │               │
│         └───────────────────┼──────────────────┘               │
│                             ▼                                  │
│                    ┌─────────────────┐                        │
│                    │   ChromaDB      │                        │
│                    │  Vector Store   │                        │
│                    │ (chroma_db/)    │                        │
│                    └────────┬────────┘                        │
│                             │                                  │
└─────────────────────────────┼──────────────────────────────────┘
                              │
                    OUTPUT → QUERY
                    ────────  ─────
                              │
┌─────────────────────────────┼──────────────────────────────────┐
│                    QUERY PIPELINE                               │
├─────────────────────────────┼──────────────────────────────────┤
│                             │                                   │
│  User Query (string)        ▼                                   │
│      │                 ┌──────────┐                            │
│      │                 │ Embed    │                            │
│      │                 │ Query    │                            │
│      │                 └─────┬────┘                            │
│      │                       ▼                                  │
│      │              Query Vector (384 dims)                    │
│      │                       │                                  │
│      │        ┌──────────────┴──────────────┐                  │
│      │        ▼                             ▼                  │
│      │   ┌──────────────┐         ┌────────────────┐          │
│      │   │ Semantic     │         │  Keyword       │          │
│      │   │ Similarity   │         │  Matching      │          │
│      │   │ (Cosine)     │         │  (TF-IDF)      │          │
│      │   └──────┬───────┘         └────────┬───────┘          │
│      │          │ 0.0-1.0                  │ 0.0-1.0         │
│      │          │ (semantic_score)         │ (keyword_score) │
│      │          └──────────────┬───────────┘                  │
│      │                         ▼                               │
│      │              ┌──────────────────┐                      │
│      │              │ Hybrid Score     │                      │
│      │              │ (0.6 + 0.4)      │                      │
│      │              │ = 0.0-1.0        │                      │
│      │              └────────┬─────────┘                      │
│      │                       ▼                                  │
│      │         ┌───────────────────────┐                       │
│      │         │ Sort by Score         │                       │
│      │         │ Return Top-K          │                       │
│      │         └─────────┬─────────────┘                       │
│      │                   ▼                                      │
│      │          Top-K Relevant Bids                            │
│      │          (with scores)                                  │
│      │                   │                                      │
│      └─────────┬─────────┘                                     │
│              ┌─▼────────┐                                      │
│              │ Format   │                                      │
│              │ Results  │                                      │
│              └─┬────────┘                                      │
│                ├─→ Direct (retrieval-only)                     │
│                │   Print bids + scores                        │
│                │                                              │
│                └─→ With LLM                                   │
│                    ┌──────────────┐                           │
│                    │ Send to LLM  │                           │
│                    │ (OpenAI or   │                           │
│                    │ Ollama)      │                           │
│                    └──────┬───────┘                           │
│                           ▼                                    │
│                  Generate Natural                             │
│                  Language Answer                              │
│                           │                                    │
└───────────────────────────┼────────────────────────────────────┘
                            │
                            ▼
                      ┌────────────────┐
                      │ OUTPUT         │
                      │ - Answer text  │
                      │ - Source bids  │
                      │ - Scores       │
                      └────────────────┘
```

---

## Scoring Components Breakdown

```
HYBRID SCORING FORMULA
═════════════════════════════════════════════════════════════════

                        ┌─────────────┐
                        │ User Query  │
                        └──────┬──────┘
                               │
                ┌──────────────┴──────────────┐
                │                             │
                ▼                             ▼
         ┌─────────────────┐         ┌──────────────┐
         │ SEMANTIC TRACK  │         │ KEYWORD TRACK│
         └────────┬────────┘         └──────┬───────┘
                  │                         │
         1. Embed query vector       1. Split query to words
            (384 dims)               2. Remove stop words
         2. Cosine distance to       3. Find matches in:
            each chunk vector           - full_item_name (w=3.0)
         3. Convert to score            - department (w=1.5)
            score = 1 - distance        - bid_type (w=1.0)
                                         - product_type (w=1.0)
                  │                   4. Calculate match %
                  │                   5. Apply field weights
                  │                   6. Normalize 0-1
                  │                      │
         semantic_score        keyword_score
         (0.0 to 1.0)          (0.0 to 1.0)
                  │                      │
                  └──────────────┬───────┘
                                 ▼
                  ┌─────────────────────────┐
                  │  COMBINE (60% + 40%)   │
                  │                        │
                  │ hybrid = (semantic *   │
                  │          0.6) +        │
                  │          (keyword *    │
                  │          0.4)          │
                  │                        │
                  │ Result: 0.0 to 1.0     │
                  └────────────┬───────────┘
                               │
                               ▼
                        FINAL SCORE
                        Used for ranking
```

---

## Data Flow: From PDF to Results

```
STAGE 1: INGEST
════════════════════════════════════════════════════════════════

  PDF Document (from GeM website)
          │
          ▼
  ┌─────────────────┐
  │ Extract Text    │
  │ (PyMuPDF)       │ + OCR fallback if needed
  └────────┬────────┘
           │
           ▼
  Raw PDF Text: "Bid No: GEM/2024/B/123 Item: Laptops..."
           │
           ▼
  ┌──────────────────────┐
  │ Parse Fields         │
  │ (regex patterns)     │ Extract: bid_no, item_name,
  └────────┬─────────────┘          department, dates, value
           │
           ▼
  Structured Data:
  {
    "bid_no": "GEM/2024/B/123",
    "full_item_name": "Dell Laptops",
    "department": "IT",
    "end_date": "15-12-2024 05:00:00",
    "estimated_value": "50 Lakhs",
    "full_pdf_text": "Bid No: GEM/2024/B/123..."
  }
           │
           ▼
  ┌──────────────────────┐
  │ Store in SQLite      │ Dedup check: new bid?
  └────────┬─────────────┘
           │
           ▼
  New Bid? YES → Continue to Stage 2
            NO → Stop (already indexed)

────────────────────────────────────────────────────────────────

STAGE 2: INDEX
════════════════════════════════════════════════════════════════

  Bid Document (from SQL)
           │
           ▼
  ┌──────────────────────────┐
  │ Build Bid Document       │
  │ Combine structured +     │ "Bid Number: GEM/2024/B/123
  │ PDF text into one        │  RA Number: ...
  │ rich string              │  Item: Dell Laptops
  └────────┬─────────────────┘  ... [full PDF text]"
           │
           ▼
  ┌──────────────────────────┐
  │ Chunk Text               │
  │ Split into overlapping   │ Chunk 1: chars 0-800
  │ windows                  │ Chunk 2: chars 700-1500
  └────────┬─────────────────┘ Chunk 3: chars 1400-2200
           │                   ... etc (overlap=100)
           ▼
  List of 5-10 chunks
  (depends on PDF size)
           │
           ▼
  ┌──────────────────────────┐
  │ Embed Chunks             │
  │ Convert each chunk to    │ Chunk 1: [0.23, -0.45, ...]
  │ 384-dim vector           │ Chunk 2: [0.31, -0.22, ...]
  └────────┬─────────────────┘ Chunk 3: [0.19, -0.51, ...]
           │
           ▼
  ┌──────────────────────────┐
  │ Upsert to ChromaDB       │
  │ Store:                   │ ID: "GEM/2024/B/123__chunk_0"
  │ - IDs                    │ Embedding: [0.23, -0.45, ...]
  │ - Embeddings             │ Text: "Bid Number: ... Item: ..."
  │ - Documents (chunks)     │ Metadata: {bid_no, dept, ...}
  │ - Metadata               │
  └────────┬─────────────────┘
           │
           ▼
  ChromaDB Collection Updated
  Now searchable!

────────────────────────────────────────────────────────────────

STAGE 3: SEARCH
════════════════════════════════════════════════════════════════

  User Query: "IT Laptops"
           │
           ▼
  ┌─────────────────────┐
  │ Embed Query         │ Query vector: [0.27, -0.38, ...]
  └────────┬────────────┘
           │
           ▼
  ┌──────────────────────────┐
  │ ChromaDB Query           │
  │ Find nearest chunks by   │ Returns 20 chunks
  │ cosine distance          │ (fetch more than top_k
  └────────┬─────────────────┘  to account for dedup)
           │
           ▼
  Raw Results:
  - Bid 1 chunk 0: distance=0.12, score=(1-0.12)=0.88
  - Bid 1 chunk 1: distance=0.15, score=(1-0.15)=0.85
  - Bid 2 chunk 0: distance=0.91, score=(1-0.91)=0.09
  - ... more chunks
           │
           ▼
  ┌──────────────────────────┐
  │ Calculate Keyword Scores │ For each chunk's metadata
  │ (TF-IDF style)           │
  └────────┬─────────────────┘
           │
           ▼
  Hybrid Scores:
  - Bid 1 chunk 0: (0.88*0.6) + (0.95*0.4) = 0.906 ✓
  - Bid 1 chunk 1: (0.85*0.6) + (0.93*0.4) = 0.882 ✓
  - Bid 2 chunk 0: (0.09*0.6) + (0.10*0.4) = 0.094 ✗
           │
           ▼
  ┌──────────────────────────┐
  │ Deduplicate by Bid ID    │
  │ Keep highest score       │ Bid 1: 0.906 (from chunk 0)
  │ per bid                  │ Bid 2: 0.094 (from chunk 0)
  └────────┬─────────────────┘ Bid 3: 0.542 ...
           │
           ▼
  ┌──────────────────────────┐
  │ Sort by Score            │ Result 1: Bid 1 (0.906)
  │ Return Top-K             │ Result 2: Bid 3 (0.542)
  └────────┬─────────────────┘ Result 3: Bid 5 (0.381)
           │                   Result 4: Bid 2 (0.094)
           │                   Result 5: Bid 7 (0.078)
           ▼
  Top-K Results (top_k=5)

────────────────────────────────────────────────────────────────

STAGE 4: GENERATE (Optional)
════════════════════════════════════════════════════════════════

  Top-K Results
           │
           ├─ If RAG_LLM_PROVIDER = "" → Go to OUTPUT (retrieval-only)
           │
           └─ If RAG_LLM_PROVIDER = "ollama" or "openai"
                      │
                      ▼
           ┌──────────────────────────┐
           │ Format Prompt            │
           │ Combine:                 │ "Bid No: GEM/2024/B/123
           │ - Question               │  Item: Dell Laptops
           │ - Top-K bids             │  Dept: IT
           │ - System instructions    │  ... [all top-K bids]
           └────────┬─────────────────┘
                    │
                    ▼
           ┌──────────────────────────┐
           │ Send to LLM              │ Call Ollama or OpenAI API
           │ (HTTP request)           │ with full prompt
           └────────┬─────────────────┘
                    │
                    ▼
           Natural Language Answer
           "Based on the retrieved bids,
            here are the IT department
            laptop procurement options..."
```

---

## Embedding Model Comparison

```
Model Selection Trade-offs
════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────┐
│ all-MiniLM-L6-v2 (DEFAULT) ⭐                              │
├──────────┬──────────┬─────────┬────────┬──────────┬─────────┤
│ Size     │ Speed    │ Quality │ Memory │ Download │ Score   │
├──────────┼──────────┼─────────┼────────┼──────────┼─────────┤
│ 22 MB    │ ⚡⚡⚡   │ 8/10   │ Low    │ Yes      │ 8/10    │
└──────────┴──────────┴─────────┴────────┴──────────┴─────────┘
Best for: Speed, basic CPU machines, most use cases
Use when: Default choice unless specific needs

┌─────────────────────────────────────────────────────────────┐
│ all-mpnet-base-v2 (ACCURATE) 🎯                            │
├──────────┬──────────┬─────────┬────────┬──────────┬─────────┤
│ Size     │ Speed    │ Quality │ Memory │ Download │ Score   │
├──────────┼──────────┼─────────┼────────┼──────────┼─────────┤
│ 430 MB   │ ⚡⚡     │ 9/10   │ High   │ ~1 min   │ 9/10    │
└──────────┴──────────┴─────────┴────────┴──────────┴─────────┘
Best for: Accuracy over speed, better semantic understanding
Use when: Results not good enough with MiniLM
Drawback: 20x slower, reindex required

┌─────────────────────────────────────────────────────────────┐
│ all-MiniLM-L12-v2 (BALANCED)                               │
├──────────┬──────────┬─────────┬────────┬──────────┬─────────┤
│ Size     │ Speed    │ Quality │ Memory │ Download │ Score   │
├──────────┼──────────┼─────────┼────────┼──────────┼─────────┤
│ 33 MB    │ ⚡⚡     │ 8.5/10 │ Low    │ Yes      │ 8.5/10  │
└──────────┴──────────┴─────────┴────────┴──────────┴─────────┘
Best for: Balance between MiniLM and mpnet
Use when: MiniLM too weak, mpnet too slow

┌─────────────────────────────────────────────────────────────┐
│ paraphrase-multilingual-MiniLM-L12-v2 🌍                   │
├──────────┬──────────┬─────────┬────────┬──────────┬─────────┤
│ Size     │ Speed    │ Quality │ Memory │ Download │ Score   │
├──────────┼──────────┼─────────┼────────┼──────────┼─────────┤
│ 63 MB    │ ⚡⚡     │ 8/10   │ Medium │ ~30 sec  │ 7/10    │
└──────────┴──────────┴─────────┴────────┴──────────┴─────────┘
Best for: Multi-language support
Use when: Queries or docs might be in different languages
```

---

## Query Intent Detection

```
SMART TOP_K SELECTION
════════════════════════════════════════════════════════════════

User Query Input
        │
        ▼
┌─────────────────────────────────┐
│ Pattern Matching                │
└─────────────────────────────────┘
        │
    ┌───┼───┐
    │   │   │
    ▼   ▼   ▼

LISTING INTENT?            FOCUSED INTENT?        DEFAULT
───────────────            ──────────────         ───────
Keywords:                  Keywords:              Standard
- all                      - bid number           top_k
- every                    - bid no               value
- list                     - specific
- show all                 - find bid
- how many                 - this bid
- complete list
- give me all
- display all
    │                          │                      │
    ▼                          ▼                      ▼
top_k = 15              top_k = top_k // 2      top_k = 5
(more results)          (fewer results)          (balanced)

Example:                Example:                 Example:
"Show all IT bids"      "Find bid GEM/2024"      "IT bids"
→ top_k = 15            → top_k = 2-3            → top_k = 5
→ Comprehensive         → Precise                → Balanced
→ May include noise     → Only best matches      → Good mix

Result: Adaptive behavior based on query intent
        Minimum manual tuning needed
```

---

## Configuration Decision Tree

```
WHERE DO I START?
════════════════════════════════════════════════════════════════

                           START
                            │
                ┌───────────┴───────────┐
                │                       │
                ▼                       ▼
        Results look       Results look
        good?              bad?
            │                   │
            ▼                   ▼
        ┌─────────┐         ┌─────────────────┐
        │ SKIP TO │         │ WHAT'S WRONG?   │
        │PROD SET │         └────────┬────────┘
        └─────────┘                  │
                          ┌─────────┬┴─────────┐
                          │         │         │
                          ▼         ▼         ▼
                    Too    Wrong   Too
                    broad  type    slow
                    │      │       │
            ┌───────┴──┐   │   ┌───┴──────┐
            ▼          ▼   ▼   ▼          ▼
          Try:       Try: Try:
        1. Lower   1. Boost 1. Remove
          top_k     type     LLM
        2. Boost     weight
           semantic 2. Add  2. Fewer
        3. Filter  filter   chunks
                   3. Lower
                     keyword
                     weight

        Did it improve?
            │
        ┌───┴───┐
        │       │
        ▼       ▼
       YES      NO
        │       │
        ▼       ▼
      Keep    Revert
      Try     Try
      next    different
      change  change

Iterate until happy!
```

---

## Performance Tuning Map

```
YOUR GOAL                    WHAT TO CHANGE
═════════════════════════════════════════════════════════════════

Faster queries              │ RAG_LLM_PROVIDER = ""
                            │ RAG_CHUNK_SIZE = 400
                            │ RAG_TOP_K = 3

Better accuracy             │ RAG_EMBEDDING_MODEL = all-mpnet
                            │ Increase top_k to 10-15
                            │ hybrid = 0.8 semantic, 0.2 keyword
                            │ (requires reindex)

More results                │ RAG_TOP_K = 20
                            │ Decrease semantic weight
                            │ Larger chunk size

Fewer, better results       │ RAG_TOP_K = 2-3
                            │ Increase semantic weight
                            │ Smaller chunk size

Filter by type/dept         │ --filter product_type=Product
                            │ Boost type field weights

Prevent dupes               │ python main.py --reindex

No results?                 │ python main.py --reindex
                            │ python main.py --stats
                            │ Check RAG_TOP_K not too low
```

---

## Scoring Dynamics (Visual)

```
How different factor combinations affect results:

                    HIGH SEMANTIC (0.8)
                    ↑
                    │
        BROAD       │  Finds many related      NARROW
        RESULTS     │  concepts, may be        RESULTS
                    │  vague in specifics
                    │
                    │         ★ DEFAULT
                    │     (0.6 semantic)
                    │
                    │  Good balance: specific
                    │  AND related concepts
                    │
        ────────────┼──────────────────────────────────
        NO EXACT    │      HIGH KEYWORD (0.8)
        MATCHES     │
        BUT         │  Requires exact words,
        CONCEPTS    │  misses synonyms
        SIMILAR     │
                    │   LOW KEYWORD (0.2)
                    │  Fuzzy matches, lots of noise
                    │
                    ▼
        LOW SEMANTIC (0.3)

Positioning in this space determines result characteristics.
```

---

## ChromaDB Index Health Monitoring

```
CHECKING INDEX HEALTH
════════════════════════════════════════════════════════════════

Command: python main.py --stats

Output looks like:
┌──────────────────────────────────────┐
│ GeM Bid Scraper — Stats              │
├──────────────────────────────────────┤
│ SQLite total bids      : 542         │
│ Vector store chunks    : 1847        │
│ Ratio                  : 3.4:1       │  ← Important!
└──────────────────────────────────────┘

INTERPRETATION:
───────────────

Ratio 2-6:1    ✓ HEALTHY
               Each bid has 2-6 chunks (normal with overlap)
               Continue using normally

Ratio > 10:1   ⚠️  SUSPICIOUS
               Too many chunks per bid
               Possible: Duplicate chunks in index
               Fix: python main.py --reindex

Ratio < 1:1    ❌ ERROR
               More bids than chunks (impossible!)
               Possible: Data corruption
               Fix: python main.py --reindex

Chunks not    ❌ NOT INDEXING
growing with   New bids scraped but not indexed
new bids       Check: Logs for errors
               Fix: Rescrape + verify indexing
```

---

## Quick Parameter Impact Matrix

```
Parameter          Impact Area             Impact Level
═════════════════════════════════════════════════════════════

RAG_TOP_K          Result count            MEDIUM
                   Precision/Recall
                   Query speed

RAG_CHUNK_SIZE     Indexing speed          HIGH (if changed)
                   Context per chunk       Requires reindex
                   Index size

RAG_CHUNK_OVERLAP  Context preservation    MEDIUM
                   Index size              Requires reindex
                   Retrieval quality

Semantic weight    Result relevance        HIGH
                   Synonym matching        No reindex
                   Result ordering

Keyword weight     Exact match priority    HIGH
                   Field sensitivity       No reindex

Field weights      Type/dept importance    HIGH
                   Keyword scoring         No reindex

Embedding model    Accuracy                CRITICAL
                   Speed                   Requires reindex
                   Language support

LLM provider       Answer quality          MEDIUM (cosmetic)
                   Query speed             No reindex
                   Cost

Top-K at query     Result count            MEDIUM
time               Overrides config        No reindex
```

---

## Getting Help Decision Tree

```
Something went wrong?
        │
        ├─ "Vector store is empty"
        │  └─→ python main.py --reindex
        │
        ├─ "Results are wrong"
        │  ├─→ Read: RAG_SCORING_EXAMPLES.md
        │  └─→ Follow: RAG_TUNING_GUIDE.md
        │
        ├─ "System is slow"
        │  ├─→ Check: RAG_LLM_PROVIDER=""?
        │  ├─→ Try: Smaller chunks
        │  └─→ Try: Fewer results (top_k=3)
        │
        ├─ "Getting duplicates"
        │  └─→ python main.py --reindex
        │
        ├─ "LLM returns nonsense"
        │  ├─→ Try: Different OLLAMA_MODEL
        │  ├─→ Try: RAG_LLM_PROVIDER=""
        │  └─→ Check: SYSTEM_PROMPT in llm.py
        │
        ├─ "No results for valid query"
        │  ├─→ python main.py --stats
        │  ├─→ python main.py --reindex
        │  └─→ Try: Lower top_k to 1
        │
        └─ "Can't find query docs"
           ├─→ Use: /search command (retrieval only)
           ├─→ Check: Filters are correct
           └─→ Try: Simpler query
```

---

## File Purpose Quick Reference

```
CODEBASE ORGANIZATION
════════════════════════════════════════════════════════════════

FOR TUNING:
  config/settings.py ........... All configuration values (.env)
  rag/vector_store.py ......... Hybrid scoring formula (line ~158)
  rag/query_engine.py ......... Query logic + smart top_k

FOR UNDERSTANDING:
  rag/embedder.py ............ Embedding & chunking logic
  rag/llm.py ................. LLM integration
  storage/database.py ........ SQLite operations
  core/parser.py ............ PDF parsing

FOR RUNNING:
  main.py .................... All commands here
  pipeline/scraper.py ....... Scraping logic (if tweaking scraper)

FOR REFERENCE (You created these):
  RAG_ARCHITECTURE_GUIDE.md .. How system works (theory)
  RAG_SCORING_EXAMPLES.md ... Scoring with real examples
  RAG_TUNING_GUIDE.md ....... How to tune (practical)
  RAG_QUICK_START.md ........ Fast reference (commands)
  (This file) ............... Visual diagrams
```

---

## Summary of Visual References

This document contains:

1. **System Architecture** (Top-level overview)
2. **Scoring Components** (How scores calculated)
3. **Data Flow** (From PDF to results, stage by stage)
4. **Embedding Models** (Comparison table)
5. **Query Intent Detection** (Smart top_k selection)
6. **Configuration Decision Tree** (What to change)
7. **Performance Map** (Goals to changes)
8. **Scoring Dynamics** (Visual positioning)
9. **Index Health Monitoring** (Stats interpretation)
10. **Parameter Impact Matrix** (What each change does)
11. **Help Decision Tree** (Troubleshooting)
12. **File Organization** (Where to find things)

**Total**: 12 visual reference guides covering all aspects of the system!

