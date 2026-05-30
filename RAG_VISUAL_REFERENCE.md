# RAG System — Visual Reference & Architecture Diagrams

> Quick visual guides for understanding the system  
> **Last Updated**: May 2026

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
│  (active bids  │ (browser.py) │   │                            │
│   only via     └─────────────┘    │                            │
│   Ongoing                         ▼                            │
│   Bids/RA                ┌─────────────┐                       │
│   filter)                │  Parser     │────┐                  │
│                          │(parser.py)  │    │                  │
│                          └─────────────┘    │                  │
│                          ↑ dates from       ▼                  │
│                          card HTML   SQLite DB                 │
│                                      (database.py)            │
│                                             ↓                  │
│                                    ┌─────────────────────┐    │
│                                    │ RAG Indexing        │    │
│                                    │ (embedder.py)       │    │
│                                    └────────┬────────────┘    │
│                                             ↓                  │
│                                    ┌─────────────────────┐    │
│                                    │   ChromaDB          │    │
│                                    │  Vector Store       │    │
│                                    │ (chroma_db/)        │    │
│                                    └────────┬────────────┘    │
└─────────────────────────────────────────────┼──────────────────┘
                                              │
                              QUERY PIPELINE  ▼
┌─────────────────────────────────────────────────────────────────┐
│  User Query ──→ Exit Check ──→ Smart top_k ──→ Embed Query     │
│                                                      │          │
│                              ┌───────────────────────┘          │
│                              ▼                                   │
│                    ┌──────────────────┐                         │
│                    │  Hybrid Search   │                         │
│                    │  Semantic (60%)  │                         │
│                    │  Keyword  (40%)  │                         │
│                    └────────┬─────────┘                         │
│                             ▼                                    │
│                    Deduplicate → Sort → Top-K                   │
│                             │                                    │
│              ┌──────────────┴──────────────┐                    │
│              ▼                             ▼                    │
│        LLM Answer                  Retrieval-Only               │
│     (Ollama/OpenAI)              (score breakdown)              │
└─────────────────────────────────────────────────────────────────┘
```

---

## Scraper Flow: Active Bids + Card Dates

```
SCRAPER PIPELINE (pipeline/scraper.py)
════════════════════════════════════════════════════════════════

For each BID_TYPE in settings:
        │
        ▼
┌─────────────────────────┐
│ browser.reset_filters() │
└────────┬────────────────┘
         │
         ▼
┌──────────────────────────────┐
│ browser.select_bid_type()    │  e.g. "Product Bid/RAs"
└────────┬─────────────────────┘
         │
         ▼
┌──────────────────────────────┐
│ browser.select_ongoing_bids()│  ← NEW: filters active bids only
│ Clicks "Ongoing Bids/RA"     │       (expired bids skipped)
└────────┬─────────────────────┘
         │
         ▼
  For each card on page:
         │
         ├─ get_ra_from_card()          ← RA number from card HTML
         ├─ get_product_type_from_card() ← product type from card HTML
         ├─ get_dates_from_card()        ← START + END dates from card HTML
         │    ├─ Matches "Start Date: DD-MM-YYYY HH:MM AM/PM"
         │    ├─ Matches "End Date: DD-MM-YYYY HH:MM AM/PM"
         │    └─ Converts to 24h via _to_24h()
         │
         ├─ browser.extract_card_links() ← document_url + corrigendum_url
         ├─ browser.download_pdf()
         ├─ extract_pdf_text()           ← PyMuPDF + OCR fallback
         ├─ parse_bid_data()             ← regex field extraction
         │
         └─ Build bid record:
              start_date = card_start OR pdf_start  (card preferred)
              end_date   = card_end   OR pdf_end    (card preferred)
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
         ┌─────────────────┐         ┌──────────────────┐
         │ SEMANTIC TRACK  │         │  KEYWORD TRACK   │
         └────────┬────────┘         │  _keyword_score()│
                  │                  └──────┬───────────┘
                  │                         │
         1. Embed query vector       1. Split query to words
            (384 dims)               2. Remove stop words:
         2. Cosine distance to          {for,the,a,an,and,
            each chunk vector            or,in,of,is}
         3. Convert to score         3. If all stop words →
            score = 1 - distance        return 0.5 (neutral)
                                     4. Find matches in:
                                        full_item_name (w=3.0)
                                        department     (w=1.5)
                                        bid_type       (w=1.0)
                                        product_type   (w=1.0)
                  │                   5. Normalize 0-1
                  │                      │
         semantic_score        keyword_score
         (0.0 to 1.0)          (0.0 to 1.0)
                  │                      │
                  └──────────────┬───────┘
                                 ▼
                  ┌─────────────────────────┐
                  │  COMBINE (60% + 40%)    │
                  │                         │
                  │ hybrid = (semantic *    │
                  │          0.6) +         │
                  │          (keyword *     │
                  │          0.4)           │
                  │                         │
                  │ Result: 0.0 to 1.0      │
                  └────────────┬────────────┘
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

  GeM Portal Card HTML
          │
          ├─ get_dates_from_card()
          │    start_date = "11-12-2025 16:30:00"  (24h format)
          │    end_date   = "11-01-2026 16:00:00"
          │
          └─ PDF Document (downloaded)
                   │
                   ▼
          ┌─────────────────┐
          │ extract_pdf_text│  PyMuPDF → OCR fallback
          └────────┬────────┘
                   │
                   ▼
          ┌──────────────────────┐
          │ parse_bid_data()     │  regex extraction
          └────────┬─────────────┘
                   │
                   ▼
          Structured Data:
          {
            "bid_no":          "GEM/2026/B/7382409",
            "full_item_name":  "All in One PC (V2)",
            "department":      "Ministry of Electronics",
            "start_date":      "11-12-2025 16:30:00",  ← from card
            "end_date":        "11-01-2026 16:00:00",  ← from card
            "estimated_value": "13000000",
            "full_pdf_text":   "Bid No: GEM/2026/B/..."
          }
                   │
                   ▼
          ┌──────────────────────┐
          │ database.upsert()    │  dedup check: new bid?
          └────────┬─────────────┘
                   │
          New Bid? YES → Continue to Stage 2
                    NO → Stop (already indexed)

────────────────────────────────────────────────────────────────

STAGE 2: INDEX
════════════════════════════════════════════════════════════════

  Bid Document (from SQL)
           │
           ▼
  ┌──────────────────────────┐
  │ build_bid_document()     │  "Bid Number: GEM/2026/B/7382409
  │ Combine structured +     │   RA Number: ...
  │ PDF text into one string │   Item: All in One PC (V2)
  └────────┬─────────────────┘   ... [full PDF text]"
           │
           ▼
  ┌──────────────────────────┐
  │ chunk_text()             │  Chunk 1: chars 0-800
  │ Overlapping windows      │  Chunk 2: chars 700-1500
  └────────┬─────────────────┘  Chunk 3: chars 1400-2200
           │
           ▼
  ┌──────────────────────────┐
  │ embed_texts()            │  Chunk 1: [0.23, -0.45, ...]
  │ sentence-transformers    │  Chunk 2: [0.31, -0.22, ...]
  └────────┬─────────────────┘
           │
           ▼
  ┌──────────────────────────┐
  │ col.upsert()             │  ID: "GEM/2026/B/7382409__chunk_0"
  │ ChromaDB                 │  Embedding: [0.23, -0.45, ...]
  └────────┬─────────────────┘  Metadata: {bid_no, dept, dates...}
           │
           ▼
  ChromaDB Collection Updated — Now searchable!

────────────────────────────────────────────────────────────────

STAGE 3: SEARCH
════════════════════════════════════════════════════════════════

  User Query: "IT Laptops"
           │
           ▼
  ┌─────────────────────┐
  │ is_exit() check     │  ← checked FIRST before anything
  │ quit/bye/exit/done? │
  └────────┬────────────┘
           │ (not exit)
           ▼
  ┌─────────────────────┐
  │ _smart_top_k()      │  listing intent? → 15
  │ intent detection    │  focused lookup? → k//2
  └────────┬────────────┘  default         → 5
           │
           ▼
  ┌─────────────────────┐
  │ embed_query()       │  Query vector: [0.27, -0.38, ...]
  └────────┬────────────┘
           │
           ▼
  ┌──────────────────────────┐
  │ ChromaDB query           │  Returns fetch_n = top_k * 4 chunks
  │ cosine distance search   │
  └────────┬─────────────────┘
           │
           ▼
  For each chunk:
    semantic_score = 1 - distance
    keyword_score  = _keyword_score(query, metadata)
    hybrid_score   = (semantic * 0.6) + (keyword * 0.4)
           │
           ▼
  ┌──────────────────────────┐
  │ Deduplicate by bid_no    │  Keep highest hybrid score per bid
  │ Sort descending          │
  │ Return top_k             │
  └────────┬─────────────────┘

────────────────────────────────────────────────────────────────

STAGE 4: GENERATE (Optional)
════════════════════════════════════════════════════════════════

  Top-K Results
           │
           ├─ RAG_LLM_PROVIDER = "" → Retrieval-only output
           │   Shows: bid details + score breakdown
           │   Overall Score : 72%
           │     • Semantic (60%)  : 85%
           │     • Keyword  (40%)  : 52%
           │
           └─ RAG_LLM_PROVIDER = "ollama" or "openai"
                      │
                      ▼
           ┌──────────────────────────┐
           │ build_prompt()           │  Max 8 bids in prompt
           │ Format bids + question   │
           └────────┬─────────────────┘
                    │
                    ▼
           ┌──────────────────────────┐
           │ Call LLM                 │  Ollama or OpenAI API
           │ temperature=0.0          │  (deterministic output)
           └────────┬─────────────────┘
                    │
                    ▼
           Natural Language Answer
           (structured bid format)
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

┌─────────────────────────────────────────────────────────────┐
│ all-mpnet-base-v2 (ACCURATE) 🎯                            │
├──────────┬──────────┬─────────┬────────┬──────────┬─────────┤
│ Size     │ Speed    │ Quality │ Memory │ Download │ Score   │
├──────────┼──────────┼─────────┼────────┼──────────┼─────────┤
│ 430 MB   │ ⚡⚡     │ 9/10   │ High   │ ~1 min   │ 9/10    │
└──────────┴──────────┴─────────┴────────┴──────────┴─────────┘
Best for: Accuracy over speed, better semantic understanding
Drawback: 20x slower, reindex required

┌─────────────────────────────────────────────────────────────┐
│ all-MiniLM-L12-v2 (BALANCED)                               │
├──────────┬──────────┬─────────┬────────┬──────────┬─────────┤
│ Size     │ Speed    │ Quality │ Memory │ Download │ Score   │
├──────────┼──────────┼─────────┼────────┼──────────┼─────────┤
│ 33 MB    │ ⚡⚡     │ 8.5/10 │ Low    │ Yes      │ 8.5/10  │
└──────────┴──────────┴─────────┴────────┴──────────┴─────────┘
Best for: Balance between MiniLM and mpnet
```

---

## Query Intent Detection

```
SMART TOP_K SELECTION  (_smart_top_k in query_engine.py)
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
- list                     - GEM/YYYY
- show all                 - specific
- how many                 - find bid
- complete list            - this bid
- give me all
- display all
- what bids
- which bids
    │                          │                      │
    ▼                          ▼                      ▼
top_k = 15              top_k = top_k // 2      top_k = 5
(more results)          (fewer results)          (balanced)

Example:                Example:                 Example:
"Show all IT bids"      "Find bid GEM/2024"      "IT bids"
→ top_k = 15            → top_k = 2-3            → top_k = 5
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

Active bids only            │ Already handled automatically
                            │ browser.select_ongoing_bids()
                            │ called in scraper for every bid type
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
│ New (unseen)           : 12          │
│ Total runs logged      : 38          │
│ Vector store chunks    : 1847        │
│ ChromaDB path          : storage/... │
└──────────────────────────────────────┘

INTERPRETATION:
───────────────

chunks:bids ratio 2-6:1   ✓ HEALTHY
                           Each bid has 2-6 chunks (normal)

ratio > 10:1              ⚠️  SUSPICIOUS
                           Too many chunks per bid
                           Fix: python main.py --reindex

ratio < 1:1               ❌ ERROR
                           More bids than chunks
                           Fix: python main.py --reindex

chunks not growing        ❌ NOT INDEXING
with new bids              Check logs for errors
                           Fix: Rescrape + verify indexing
```

---

## Quick Parameter Impact Matrix

```
Parameter          Impact Area             Requires Reindex?
═════════════════════════════════════════════════════════════

RAG_TOP_K          Result count            NO
                   Precision/Recall

RAG_CHUNK_SIZE     Indexing speed          YES
                   Context per chunk
                   Index size

RAG_CHUNK_OVERLAP  Context preservation    YES
                   Index size

Semantic weight    Result relevance        NO
                   Synonym matching

Keyword weight     Exact match priority    NO
                   Field sensitivity

Field weights      Type/dept importance    NO
(_keyword_score)   Keyword scoring

Embedding model    Accuracy                YES
                   Speed

LLM provider       Answer quality          NO
                   Query speed

select_ongoing_    Scrapes active bids     N/A (scraper setting)
bids()             only (no expired)

get_dates_from_    Date accuracy           N/A (scraper setting)
card()             Card HTML > PDF dates
```

---

## File Purpose Quick Reference

```
CODEBASE ORGANIZATION
════════════════════════════════════════════════════════════════

FOR TUNING:
  config/settings.py ........... All configuration values (.env)
  rag/vector_store.py ......... Hybrid scoring + _keyword_score
  rag/query_engine.py ......... Query logic + smart top_k + exit

FOR UNDERSTANDING:
  rag/embedder.py ............ Embedding & chunking logic
  rag/llm.py ................. LLM integration + score breakdown
  storage/database.py ........ SQLite operations + auto RAG index
  core/parser.py ............ PDF parsing + card date extraction
  core/browser.py ........... Playwright + ongoing bids filter

FOR RUNNING:
  main.py .................... All commands here
  pipeline/scraper.py ....... Scraping logic (active bids only)
  pipeline/scheduler.py ..... Hourly loop + new bid alerts

FOR REFERENCE:
  RAG_ARCHITECTURE_GUIDE.md .. How system works (theory)
  RAG_SCORING_EXAMPLES.md ... Scoring with real examples
  RAG_TUNING_GUIDE.md ....... How to tune (practical)
  RAG_QUICK_START.md ........ Fast reference (commands)
  RAG_VISUAL_REFERENCE.md ... This file (diagrams)
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
        ├─ "Exit not working in chat"
        │  └─→ is_exit() checked before query in query_engine.py
        │
        ├─ "/search shows garbled text"
        │  └─→ search_only() enriches full_item_name in query_engine.py
        │
        └─ "Dates look wrong"
           └─→ Dates come from card HTML (get_dates_from_card)
               PDF dates used only as fallback
               Check: card HTML has Start Date / End Date labels
```
