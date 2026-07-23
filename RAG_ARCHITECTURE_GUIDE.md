# GeM Bid RAG System — Complete Architecture Guide

> **Last Updated:** July 2026  
> **Scope:** Full system design, all components, data flows, scoring theory, configuration  
> **For:** Engineers, architects, advanced users

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Complete Data Flow](#complete-data-flow)
3. [Component Architecture](#component-architecture)
4. [Embedding & Vector Store](#embedding--vector-store)
5. [Hybrid Scoring Mechanism](#hybrid-scoring-mechanism)
6. [Query Processing Pipeline](#query-processing-pipeline)
7. [Configuration Reference](#configuration-reference)
8. [Performance & Scaling](#performance--scaling)
9. [Troubleshooting](#troubleshooting)

---

## System Overview

Your system is a **Retrieval Augmented Generation (RAG)** pipeline for GeM bids that combines:

```
┌──────────────────────────────────────────────────────────────┐
│                  RAG SYSTEM COMPONENTS                        │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  Data Collection                  Data Processing              │
│  ────────────────                 ──────────────              │
│  • Web Scraper          →         • PDF Parser               │
│  • GeM Portal                     • Card HTML Parser         │
│  • Active Bids Filter             • Date Extraction          │
│                                   • Field Normalization      │
│                                           │                   │
│                                           ▼                   │
│                                   ┌─────────────────┐        │
│                                   │  SQLite DB      │        │
│                                   │  (gem_bids.db)  │        │
│                                   └────────┬────────┘        │
│                                            │                  │
│  Vector Embeddings          Vector Search                     │
│  ──────────────────         ──────────────                    │
│  • Sentence-Transformers    • Semantic Search (60%)          │
│  • 384-dim vectors          • Keyword Matching (40%)         │
│  • Local model              • Hybrid Scoring                 │
│  • No API keys                                               │
│          │                           │                        │
│          └─────→ ChromaDB ←──────────┘                       │
│                  (vector_store)                              │
│                                                               │
│  Query Time (User Interaction)                                │
│  ──────────────────────────────────                          │
│  Question → Embed → Search → Rank → LLM/Format → Answer     │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

### Key Characteristics

- **Active Bids Only:** Scraper uses "Ongoing Bids/RA" filter (no expired bids)
- **Card-Based Dates:** Dates from HTML cards, not PDFs (more accurate)
- **Hybrid Search:** 60% semantic + 40% keyword matching
- **Local Embeddings:** No API keys, runs completely offline
- **Optional LLM:** Works with Ollama, OpenAI, or retrieval-only mode
- **Automatic Indexing:** New bids auto-indexed into ChromaDB

---

## Complete Data Flow

### Phase 1: Scraping & Storage

```
STEP 1: BROWSER INITIALIZATION (core/browser.py)
─────────────────────────────────────────────────
├─ Launch Chromium with stealth options
├─ Disable webdriver detection flags
├─ Set random User-Agent from pool
├─ Set random viewport size
├─ Apply anti-bot delays
└─ Navigate to GeM portal

STEP 2: FILTER & NAVIGATE (core/browser.py)
──────────────────────────────────────────
For each BID_TYPE in settings (Product, Service, etc.):
  ├─ Reset filters
  ├─ Select bid_type filter
  ├─ SELECT ONGOING BIDS/RA FILTER ← Active bids only
  └─ Iterate pages while collected < TARGET_PER_TYPE

STEP 3: CARD EXTRACTION (core/parser.py)
───────────────────────────────────────
For each bid card on page:
  ├─ get_card_details():
  │  ├─ bid_no:        "GEM/2026/B/7549944"
  │  ├─ product_type:  "Product" (from card)
  │  ├─ full_item_name: "Reactor Coil..." (untruncated from popover)
  │  ├─ quantity:      "12"
  │  ├─ department:    "Ministry of..." (full name from card)
  │  └─ start_date:    "20-05-2026 14:56" (FROM CARD HTML) ← IMPORTANT
  │
  └─ get_dates_from_card():
     ├─ Find "Start Date: DD-MM-YYYY HH:MM AM/PM"
     ├─ Find "End Date: DD-MM-YYYY HH:MM AM/PM"
     └─ Convert AM/PM to 24-hour format

STEP 4: PDF DOWNLOAD & PARSING (core/parser.py & MINERU_MARKDOWN_PASER.py)
─────────────────────────────────────────────────────────────────────────────
For each card:
  ├─ browser.download_pdf()
  │  └─ Save to downloads/ folder
  ├─ extract_pdf_text():
  │  ├─ PyMuPDF (fitz) for standard PDFs
  │  ├─ Tesseract OCR for scanned PDFs
  │  ├─ MINERU_MARKDOWN_PASER.py (for VLM-based layout/table extraction)
  │  └─ Return full PDF text / structured markdown
  └─ parse_bid_data():
     ├─ Regex field extraction:
     │  ├─ ra_no:              GEM/2026/R/...
     │  ├─ bid_type:           Product Bid/RAs
     │  ├─ estimated_value:    1000000
     │  ├─ bid_packet_type:    "Two Packet Bid"
     │  └─ corrigendum_url:    (if present)
     └─ Use PDF dates ONLY as fallback for start_date/end_date

STEP 5: DATABASE UPSERT (storage/database.py)
──────────────────────────────────────────────
INSERT OR REPLACE INTO bids:
  ├─ document_url:    PRIMARY KEY (deduplication)
  ├─ bid_no:          GEM/2026/B/...
  ├─ ra_no:           GEM/2026/R/...
  ├─ bid_type:        Product Bid/RAs
  ├─ product_type:    Product
  ├─ full_item_name:  Reactor Coil...
  ├─ quantity:        12
  ├─ department:      Ministry of...
  ├─ start_date:      2026-05-20 14:56:00 (card preferred)
  ├─ end_date:        2026-05-30 16:00:00 (card preferred)
  ├─ estimated_value: 117000000
  ├─ bid_packet_type: Two Packet Bid
  ├─ corrigendum_url: (if any)
  ├─ full_pdf_text:   [entire PDF content]
  ├─ first_seen:      2026-05-30T10:12:42.291979
  ├─ is_new:          1 (if new to DB)
  └─ last_seen:       2026-05-30T10:12:42.291979 (updated)

STEP 6: RAG INDEXING (rag/vector_store.py, rag/embedder.py)
────────────────────────────────────────────────────────────
For each NEW bid:
  ├─ build_bid_document():
  │  └─ Create rich text with:
  │     ├─ Structured fields (repeated for emphasis)
  │     └─ Full PDF text body
  │     
  ├─ chunk_text(text):
  │  ├─ Split into 800-char chunks
  │  ├─ Overlap: 100 chars between chunks
  │  ├─ Min size: 20 chars (filter noise)
  │  └─ Returns: List of overlapping text chunks
  │     Example: 2400-char doc → 4 chunks with overlap
  │
  ├─ embed_texts(chunks):
  │  ├─ Load all-MiniLM-L6-v2 model
  │  ├─ Convert chunks to 384-dimensional vectors
  │  ├─ Normalize (L2 norm = 1.0)
  │  └─ Batch size: 32 for efficiency
  │
  └─ upsert_bid() to ChromaDB:
     ├─ Delete old chunks for this bid (if re-indexing)
     ├─ Create IDs: "{bid_no}__chunk_{i}"
     └─ Store in ChromaDB:
        ├─ Embeddings: 384-dim vectors
        ├─ Documents: text chunks
        └─ Metadata:
           ├─ bid_no:          (for dedup)
           ├─ document_url:    (for linking)
           ├─ full_item_name:  (for /search display)
           ├─ department:      (for keyword scoring)
           ├─ bid_type:        (for keyword scoring)
           ├─ product_type:    (for keyword scoring)
           ├─ end_date:        (for display)
           └─ relevance_score: (calculated at query)

RESULT: SQLite DB + ChromaDB vector store ready for queries
```

### Phase 2: Query Processing

```
STEP 1: USER INPUT
────────────────
python main.py --ask "IT hardware bids"
        or
python main.py --chat
You > "laptop bids from NIC"

STEP 2: EXIT DETECTION (query_engine.py)
────────────────────────────────────────
Check if input is exit word:
  ├─ quit, exit, q, bye, goodbye, stop, close, end, done, ok bye
  └─ If matched → exit immediately (NO query made)
  └─ Checked BEFORE any other processing ← FIX

STEP 3: SMART TOP_K SELECTION (query_engine.py)
───────────────────────────────────────────────
Analyze question intent:
  ├─ List intent (show all, list, how many, every):
  │  └─ top_k = max(5, 15) = 15
  ├─ Focused lookup (bid number, GEM/, specific):
  │  └─ top_k = max(1, 5//2) = 2
  └─ Generic query:
     └─ top_k = 5 (default)

STEP 4: QUERY EMBEDDING (rag/embedder.py)
─────────────────────────────────────────
├─ Load sentence-transformers model
├─ Encode question → 384-dim vector
└─ This vector is used for similarity search

STEP 5: VECTOR SEARCH (rag/vector_store.py)
────────────────────────────────────────────
search(question, top_k=top_k, filters=filters):
  
  1. ChromaDB semantic search:
     ├─ Find top_k*4 raw chunks (over-fetch for dedup)
     ├─ Calculate cosine distance to query vector
     ├─ Convert: semantic_score = 1 - distance
     │   Range: 0 (unrelated) to 1 (perfect match)
     └─ Example: distance=0.12 → semantic_score=0.88
  
  2. Keyword matching (_keyword_score):
     ├─ Split question into words
     ├─ Remove stop words: {the,for,a,an,and,or,in,of,is}
     ├─ If ALL words are stop words → return 0.5 (neutral)
     ├─ Match remaining words against:
     │  ├─ full_item_name    (weight 3.0) ← highest
     │  ├─ department        (weight 1.5)
     │  ├─ bid_type          (weight 1.0)
     │  └─ product_type      (weight 1.0)
     └─ keyword_score = Σ(match_count × field_weight) / total_weights
        Range: 0 to 1
  
  3. Hybrid scoring:
     ├─ For each chunk:
     │  └─ hybrid = (semantic × 0.6) + (keyword × 0.4)
     └─ Deduplicate by bid_no (keep BEST chunk per bid)
  
  4. Sort by hybrid score, return top_k unique bids

STEP 6: LLM GENERATION (rag/llm.py) — OPTIONAL
────────────────────────────────────────────
If RAG_LLM_PROVIDER = "openai" or "ollama":
  
  1. Format retrieved bids:
     ├─ Take up to 8 bids
     ├─ Create structured context:
     │  └─ Bid No | Item | Dept | End Date | Value
     └─ Inject into prompt template
  
  2. Send to LLM:
     ├─ System prompt: "You are a GeM bid assistant"
     ├─ User message: Question + formatted bids
     └─ Model: llama3 (Ollama) or gpt-4o-mini (OpenAI)
  
  3. Parse LLM response:
     ├─ Extract answer text
     ├─ Format with markdown
     └─ Return to user

ELSE (retrieval-only mode):
  ├─ Return retrieved bids with score breakdown
  │  Example:
  │  Bid: GEM/2026/B/7549944
  │  Item: Reactor Coil for Soft Starter
  │  Scores:
  │    Overall: 76%
  │    • Semantic (60%): 82%
  │    • Keyword  (40%): 67%

STEP 7: OUTPUT
──────────────
Return structured result:
  ├─ question:    "IT hardware bids"
  ├─ answer:      "I found 5 IT hardware bids. Here's a summary..."
  └─ sources:     [
         {
           "bid_no":          "GEM/2026/B/7549944",
           "bid_type":        "Product Bid/RAs",
           "product_type":    "Product",
           "full_item_name":  "Reactor Coil...",
           "department":      "Ministry of...",
           "end_date":        "30-05-2026 16:00:00",
           "estimated_value": "117000000",
           "relevance_score": 0.845,
           "document_url":    "https://bidplus.gem.gov.in/..."
         },
         ...
       ]
```

---

## Component Architecture

### 1. Web Scraper (pipeline/scraper.py + core/browser.py)

---

### 3. Query Engine (rag/query_engine.py)

**Purpose**: Orchestrate the retrieval and generation pipeline.

**Components**:

#### a) **Exit Detection (checked first)**
```python
EXIT_WORDS = {"quit", "exit", "q", "bye", "goodbye",
              "stop", "close", "end", "done", "ok bye"}

is_exit(text) → bool
# Called BEFORE any query processing in --chat mode
# Prevents accidental queries when user wants to quit
```

#### b) **Smart Top-K Selection**
```python
_smart_top_k(question):
    if question contains listing intent words:
        (all, every, list, show all, how many, what bids, which bids, etc.)
        → return max(default_k, 15)
    
    elif question contains focused lookup words:
        (bid number, specific, find bid, GEM/YYYY, etc.)
        → return max(1, default_k // 2)
    
    else:
        → return default_k
```

#### c) **Ask Function**
```python
ask(question, filters=None, top_k=None):
    1. Determine top_k using smart selection
    2. Call search() with query + filters + top_k
    3. If no results → return "No relevant bids found"
    4. Call LLM with results (if configured)
    5. Extract sources with:
       - bid_no, bid_type, product_type
       - full_item_name (cleaned via _extract_item)
       - department, end_date, estimated_value
       - document_url
       - relevance_score (the hybrid score)
    6. Return structured response
```

#### d) **Search-Only Function**
```python
search_only(query, filters=None, top_k=None):
    - Similar to ask() but without LLM
    - Returns raw retrieval results
    - Enriches each result with clean full_item_name
    - Used by /search command in chat mode
```

---

### 4. LLM Integration (rag/llm.py)

**Purpose**: Generate natural language answers from retrieved bids.

**Supported Providers**:
1. **OpenAI** (GPT-4, GPT-3.5, etc.)
   - Requires `OPENAI_API_KEY`
   - Uses API calls
   - More capable but costs money

2. **Ollama** (Local LLMs)
   - Requires local Ollama installation
   - Runs locally (no API key)
   - Llama3, Mistral, etc.
   - Free but requires local setup

3. **None** (Retrieval-only)
   - No LLM provider
   - Returns formatted retrieval results with **full score breakdown**
   - Always works, no dependencies

**Score Breakdown in Retrieval-Only Mode**:
```
1. Bid No    : GEM/2026/B/7382409
   Item      : All in One PC (V2)
   Dept      : Ministry of Electronics
   Type      : Product Bid/RAs
   End Date  : 11-01-2026 16:00:00
   Est. Value: 13000000 INR
   URL       : https://bidplus.gem.gov.in/...
   ──────────────────────────────────────
   Overall Score : 72.00%
     • Semantic (60%)  : 85.00%
     • Keyword  (40%)  : 52.00%
```

**System Prompt**:
```
You are a GeM bid assistant.
Answer ONLY using the structured bid data in RETRIEVED BID CONTEXT.

Output each bid in EXACT format:
Bid No    : <value>
Item      : <value>
Dept      : <value>
Type      : <value>
End Date  : <value>
Est. Value: <value> INR
URL       : <value>
```

This ensures LLM output is:
- Structured and consistent
- Based only on retrieved data (no hallucination)
- Easy to parse programmatically

---

## Scoring Mechanism (Hybrid Scoring)

### Deep Dive: How Scores Are Calculated

When you query "Show me laptop bids", here's exactly what happens:

#### Step 1: Query Embedding
```
Query: "Show me laptop bids"
↓
Embed using sentence-transformers
↓
Query vector: [0.234, -0.156, 0.892, ..., 0.045]  (384 dimensions)
```

#### Step 2: Semantic Scoring
```
For each chunk in vector store:
    1. Calculate cosine distance between query vector and chunk vector
    2. Convert to similarity: semantic_score = 1 - distance
    
    Distance = 0   → Semantic score = 1.0 (perfect match)
    Distance = 0.5 → Semantic score = 0.5 (moderate match)
    Distance = 1.0 → Semantic score = 0.0 (no match)
```

**Why cosine similarity?**
- Measures angle between vectors (not magnitude)
- Values from -1 to 1 (normalized to 0-1)
- Works well with normalized embeddings
- Fast to compute

#### Step 3: Keyword Scoring (`_keyword_score`)
```
For each bid metadata:
    1. Extract query keywords (remove stop words)
       Stop words removed: for, the, a, an, and, or, in, of, is
       Query: "laptop bids"
       Keywords: {"laptop", "bids"}
    
    2. Check structured fields:
       - full_item_name: "Dell Laptop 15 inch"
         Match: "laptop" ✓ (1 match)
         Score contribution: 3.0 × (1/2) = 1.5
       
       - department: "IT Department"
         Match: none ✗
         Score contribution: 0
       
       - bid_type: "Product Bid/RAs"
         Match: none ✗
         Score contribution: 0
       
       - product_type: "Product"
         Match: none ✗
         Score contribution: 0
    
    3. Calculate keyword score:
       total_score = 1.5
       max_possible = 3.0 + 1.5 + 1.0 + 1.0 = 6.5
       keyword_score = min(1.0, 1.5 / 6.5) = 0.23
    
    Note: Returns 0.5 (neutral) if all query words are stop words
```

#### Step 4: Hybrid Score
```
hybrid_score = (semantic_score × 0.6) + (keyword_score × 0.4)
             = (0.87 × 0.6) + (0.23 × 0.4)
             = 0.522 + 0.092
             = 0.614
```

#### Step 5: Deduplication & Ranking
```
If same bid appears in multiple chunks:
    Keep only the chunk with highest hybrid score
    
Sort all unique bids by hybrid score (descending)

Return top_k results
```

### Weight Rationale

**Why 60% semantic + 40% keyword?**

- **Semantic (60%)**: Captures intent and meaning
  - Handles synonyms ("laptop" matches "computer")
  - Understands context
  - Works across languages theoretically
  
- **Keyword (40%)**: Catches exact matches in structured fields
  - Very important for item names
  - Prevents irrelevant results that are semantically close
  - Ensures budget-conscious queries work well
  - Favors exact department/type matches

**Example where both matter**:

```
Query: "Construction services"

Bid A: Item="Construction Labor Supply", Dept="Public Works"
  - Semantic: 0.95 (exact match in embeddings)
  - Keyword: 0.95 (both words match item name)
  - Hybrid: 0.95 ✓ GOOD

Bid B: Item="Building Architecture Design", Dept="Services"
  - Semantic: 0.82 (similar but different)
  - Keyword: 0.40 (only "services" matches)
  - Hybrid: 0.72 ✓ OKAY

Bid C: Item="Machinery Parts", Dept="Construction Industry"
  - Semantic: 0.78 (some related concepts)
  - Keyword: 0.50 ("construction" matches dept, not item)
  - Hybrid: 0.68 ✓ LOWER

Result ranking: A > B > C (correct!)
```

---

## Configuration & Tuning

### 1. Chunk Settings (affects indexing)

**File**: `.env` (or `config/settings.py` defaults)

```env
# Chunk size in characters
RAG_CHUNK_SIZE=800

# Overlap in characters
RAG_CHUNK_OVERLAP=100
```

**When to tune**:

| Setting | Current | Increase | Decrease |
|---------|---------|----------|----------|
| **CHUNK_SIZE** | 800 | When documents have long, context-dependent information | When docs are structured with short fields |
| **CHUNK_OVERLAP** | 100 | When context boundary matters (e.g., info spans edges) | When indexing speed is critical & memory is limited |

### 2. Embedding Model

```env
RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2
```

**Available models** (trade-off: size vs. quality):

| Model | Dimensions | Size | Speed | Quality | Use Case |
|-------|-----------|------|-------|---------|----------|
| `all-MiniLM-L6-v2` | 384 | 22 MB | ⚡⚡⚡ | Good | **DEFAULT** (CPU-friendly) |
| `all-mpnet-base-v2` | 768 | 430 MB | ⚡⚡ | Better | More accurate, slower |
| `all-MiniLM-L12-v2` | 384 | 33 MB | ⚡⚡ | Better | More layers, same size |
| `paraphrase-multilingual-MiniLM-L12-v2` | 384 | 63 MB | ⚡ | Good | Multi-language support |

**Important**: Changing this requires rebuilding the index!
```bash
python main.py --reindex
```

### 3. Search Settings

```env
# Number of top results to return
RAG_TOP_K=5
```

**When to tune**:

```env
RAG_TOP_K=3       # Returns fewer, higher-quality results
                  # Use when: precision > recall

RAG_TOP_K=10      # Returns more results (may include noise)
                  # Use when: recall > precision, comprehensive listing
```

### 4. Hybrid Scoring Weights

**File**: `rag/vector_store.py` (search function, hybrid score line)

Current:
```python
hybrid_score = (semantic_score * 0.6) + (keyword_score * 0.4)
```

**To adjust weights**:

```python
# Make keyword matching more important
hybrid_score = (semantic_score * 0.5) + (keyword_score * 0.5)

# Make semantic matching more important
hybrid_score = (semantic_score * 0.7) + (keyword_score * 0.3)
```

### 5. Keyword Field Weights

**File**: `rag/vector_store.py` (`_keyword_score` function)

```python
fields_text = {
    "full_item_name": 3.0,    # Match item name heavily
    "department": 1.5,
    "bid_type": 1.0,
    "product_type": 1.0,
}
```

### 6. LLM Provider Settings

```env
# Options: "openai", "ollama", or "" (empty for retrieval-only)
RAG_LLM_PROVIDER=ollama

# For OpenAI:
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# For Ollama:
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
```

**Provider comparison**:

| Provider | Setup | Cost | Speed | Quality |
|----------|-------|------|-------|---------|
| **ollama** | Install locally | Free | Medium | Good |
| **openai** | API key | $$ | Fast | Excellent |
| **None** | N/A | Free | Fast | N/A (retrieval-only with score breakdown) |

---

## Performance Optimization

### 1. Indexing Performance

```python
# Use batch processing (already done in code)
embeddings = model.encode(
    texts,
    batch_size=32,        # Process 32 chunks at once
    normalize_embeddings=True,  # Cosine-ready
)
```

**Specific tuning**:

```env
# Smaller embedding model = faster indexing
RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2  # Fast
# vs
RAG_EMBEDDING_MODEL=all-mpnet-base-v2  # Accurate but slower
```

### 2. Search Performance

```python
# Current code already optimizes:
fetch_n = min(top_k * 4, total)  # Limit raw fetch to account for dedup
```

### 3. Filtering Performance

**Using filters reduces search space**:

```bash
# Slow: Search all chunks
python main.py --ask "IT bids"

# Fast: Search only Product type chunks
python main.py --ask "IT bids" --filter product_type=Product

# Why faster: ChromaDB applies filter before similarity search
```

---

## Troubleshooting & Best Practices

### Common Issues & Solutions

#### Issue 1: "Vector store is empty"

```bash
python main.py --reindex
# Or: Run full scrape first
python main.py --once
```

#### Issue 2: Results are irrelevant or too narrow

```
Likely causes:
1. Hybrid weights too biased toward keyword
   → Try: hybrid_score = (semantic * 0.7) + (keyword * 0.3)

2. top_k too small
   → Try: RAG_TOP_K=10

3. Embedding model too generic
   → Try: all-mpnet-base-v2 (better quality, requires reindex)

4. Query is too specific/ambiguous
   → Try: Broaden query ("IT hardware" → "IT equipment")
```

#### Issue 3: Same bid appears multiple times

```bash
python main.py --stats
# Ratio chunks:bids should be 3-5:1
# If abnormal:
python main.py --reindex
```

#### Issue 4: Query returns results in wrong order

```python
# Option A: Adjust hybrid weights
hybrid_score = (semantic_score * 0.7) + (keyword_score * 0.3)

# Option B: Use filters
# python main.py --ask "bids" --filter product_type=Product

# Option C: Adjust keyword field weights
fields_text = {
    "full_item_name": 4.0,    # Increase if item name match most important
    "department": 1.5,
    "bid_type": 1.0,
    "product_type": 1.0,
}
```

#### Issue 5: LLM returns hallucinated information

Check `SYSTEM_PROMPT` in `rag/llm.py` includes:
- `"Answer ONLY using the structured bid data in RETRIEVED BID CONTEXT."`
- `"Never hallucinate values not in the context."`

Or switch to retrieval-only: `RAG_LLM_PROVIDER=""`

#### Issue 6: Slow searches

```env
# Option 1: Faster LLM
OLLAMA_MODEL=tinyllama

# Option 2: No LLM (instant results)
RAG_LLM_PROVIDER=""

# Option 3: Fewer results
RAG_TOP_K=3
```

### Best Practices

#### Re-indexing Strategy

```
✓ DO reindex when:
  - Changing RAG_EMBEDDING_MODEL
  - Changing RAG_CHUNK_SIZE / RAG_CHUNK_OVERLAP
  - Noticed data corruption

✗ DON'T reindex when:
  - Just changing top_k, weights, LLM settings
  - Just updating filters
  - Scraping new bids (automatic)
```

```bash
python main.py --reindex
# Takes time proportional to # of bids
# (~2-3 min for 1000 bids on CPU)
```

---

## Summary Table: When to Change What

| Goal | Parameter | Change | Requires Reindex |
|------|-----------|--------|-----------------|
| **Faster indexing** | RAG_CHUNK_SIZE | 800→600 | Yes |
| **Faster indexing** | RAG_EMBEDDING_MODEL | mpnet→MiniLM | Yes |
| **Better accuracy** | RAG_EMBEDDING_MODEL | MiniLM→mpnet | Yes |
| **More results** | RAG_TOP_K | 5→15 | No |
| **Fewer results** | RAG_TOP_K | 5→3 | No |
| **Semantic priority** | Hybrid weights | 0.6→0.7 semantic | No |
| **Keyword priority** | Hybrid weights | 0.4→0.5 keyword | No |
| **Item name priority** | Field weights | full_item_name 3.0→5.0 | No |
| **Dept priority** | Field weights | department 1.5→2.5 | No |
| **No LLM cost** | RAG_LLM_PROVIDER | ollama→"" | No |
