# GeM Bid RAG System — Complete Architecture Guide

> **Last Updated:** August 2026  
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
│  • Playwright Stealth Scraper →   • Mineru VLM Engine        │
│  • GeM Portal                     • PyMuPDF Link Extractor   │
│  • Active Bids Filter             • 24h Card HTML Parser     │
│                                   • Structured 10-Sec Parser │
│                                           │                   │
│                                           ▼                   │
│                                   ┌─────────────────┐        │
│                                   │  SQLite DB      │        │
│                                   │  (gem_bids.db)  │        │
│                                   └────────┬────────┘        │
│                                            │                  │
│  Vector & Hybrid Search       Cross-Encoder Reranking         │
│  ──────────────────────       ───────────────────────         │
│  • BAAI/bge-base-en-v1.5      • BAAI/bge-reranker-base        │
│  • BM25Okapi Sparse Retrieval • Sigmoid logit conversion      │
│  • Reciprocal Rank Fusion     • Relative 70% Cutoff Filter    │
│  • Local offline models                                       │
│          │                           │                        │
│          └─────→ ChromaDB ←──────────┘                       │
│                  (vector_store)                              │
│                                                               │
│  Query Time (User Interaction)                                │
│  ──────────────────────────────────                          │
│  Question → Embed → Hybrid Search → Rerank → LLM → Answer    │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

### Key Characteristics

- **Active Bids Only:** Scraper uses "Ongoing Bids/RA" filter (skips closed/expired tenders)
- **Card-Based Dates:** 24h formatted start/end dates from HTML card popovers (`get_dates_from_card()`)
- **Mineru VLM Conversion:** High-precision PDF layout & table extraction in Zero Save Mode with vLLM acceleration
- **PyMuPDF Link Extraction:** Extracts clickable URI links and injects `## Hyperlinks` into Markdown
- **Hybrid Retrieval & Reranking:** BGE Dense + BM25 Sparse + RRF + BAAI Cross-Encoder Reranker
- **Local Offline Models:** Runs completely offline without external embedding API keys
- **Multi-Artifact Storage:** Artifact subfolder `downloads/<safe_bid_no>/` (.html, .pdf, .md, .json)

---

## Complete Data Flow

### Phase 1: Scraping & Storage

```
STEP 1: BROWSER INITIALIZATION (core/browser.py)
─────────────────────────────────────────────────
├─ Launch Chromium with stealth options
├─ Disable webdriver detection flags (stealth JS injection)
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
  │  └─ start_date:    "20-05-2026 14:56:00" (FROM CARD HTML)
  │
  └─ get_dates_from_card():
     ├─ Find "Start Date: DD-MM-YYYY HH:MM AM/PM"
     ├─ Find "End Date: DD-MM-YYYY HH:MM AM/PM"
     └─ Convert AM/PM to 24-hour format (DD-MM-YYYY HH:MM:SS)

STEP 4: VLM CONVERSION & LINK EXTRACTION (pipeline/scraper.py)
─────────────────────────────────────────────────────────────
For each card:
  ├─ browser.download_pdf() → Save to downloads/<safe_bid_no>/<safe_bid_no>.pdf
  ├─ PyMuPDF (fitz) extract_hyperlinks() → extract clickable URIs
  ├─ Mineru VLM async_convert_document() → Zero Save Mode PDF conversion
  ├─ inject_hyperlinks_into_markdown() → inject ## Hyperlinks section into Markdown
  ├─ parse_bid_data() → 10-section structured schema extraction with _expand_table_grid()
  └─ Save artifacts: <safe_bid_no>.html, .pdf, .md, .json

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
  ├─ start_date:      20-05-2026 14:56:00
  ├─ end_date:        30-05-2026 16:00:00
  ├─ estimated_value: 117000000
  ├─ bid_packet_type: Two Packet Bid
  ├─ corrigendum_url: (if any)
  ├─ full_pdf_text:   [entire PDF Markdown content]
  ├─ first_seen:      ISO timestamp
  ├─ is_new:          1 (if new to DB)
  └─ last_seen:       ISO timestamp

STEP 6: HYBRID VECTOR & BM25 INDEXING (rag/vector_store.py, rag/embedder.py)
───────────────────────────────────────────────────────────────────────────
For each NEW bid:
  ├─ build_bid_chunks(bid):
  │  ├─ chunk[0] = metadata card text (high signal for structured fields)
  │  └─ chunk[1..] = sliding windows (800 chars, 100 overlap) over PDF text
  │
  ├─ embed_texts(chunks):
  │  ├─ Load BAAI/bge-base-en-v1.5 model (local offline mode)
  │  ├─ Convert chunks to dense vectors (normalized)
  │  └─ Upsert into ChromaDB collection ('gem_bids')
  │
  └─ Invalidate BM25 cache → BM25Okapi lazily re-indexes rich metadata corpus

RESULT: SQLite DB + ChromaDB vector store + BM25 index ready for queries
```

### Phase 2: Query Processing

```
STEP 1: USER INPUT & EXIT CHECK (rag/query_engine.py)
──────────────────────────────────────────────────────
python main.py --ask "IT hardware bids"
        or
python main.py --chat
You > "laptop bids from NIC"

Check if input is exit word (quit, exit, q, bye, done):
  └─ Checked BEFORE any query processing → Exit immediately

STEP 2: SMART TOP_K SELECTION (rag/query_engine.py)
───────────────────────────────────────────────────
Analyze question intent:
  ├─ List intent ("show all", "list", "how many"): top_k = max(default_k, 15)
  ├─ Focused lookup ("bid number", "GEM/", "specific"): top_k = max(1, default_k // 2)
  └─ Default: top_k = 5

STEP 3: HYBRID SEARCH & CROSS-ENCODER RERANKING (rag/vector_store.py)
────────────────────────────────────────────────────────────────────
1. Dense Retrieval:
   ├─ BGE Query Instruction Prefixing: "Represent this sentence for searching relevant passages: "
   ├─ BAAI/bge-base-en-v1.5 search → fetch top RAG_FETCH_K (40) chunks
   └─ Compute semantic_score = 1 - cosine_distance

2. BM25 Sparse Retrieval:
   ├─ Tokenize query → search BM25Okapi metadata corpus
   └─ Compute bm25_score = min(1.0, score / 20.0)

3. Reciprocal Rank Fusion (RRF):
   ├─ Combine dense + sparse rankings: rrf = Σ 1 / (60 + rank)
   └─ Deduplicate candidates (keep best chunk per unique Bid No)

4. Cross-Encoder Reranker:
   ├─ BAAI/bge-reranker-base scores (query, chunk_doc) pairs
   └─ rerank_score = Sigmoid(logit) (0 to 1)

5. Weighted Score & Cutoff Filter:
   ├─ final_score = (rerank_score × 0.6) + (semantic_score × 0.25) + (bm25_score × 0.15)
   └─ Relative Cutoff: Drop results scoring < 70% of the top result score

STEP 4: LLM ANSWER GENERATION (rag/llm.py)
──────────────────────────────────────────
If RAG_LLM_PROVIDER = "ollama" or "openai":
   ├─ Format top candidates into prompt context
   ├─ Apply zero-hallucination system prompt & N/A field rules
   └─ Return formatted natural language answer

ELSE (retrieval-only mode):
   └─ Return structured results with score breakdown (Rerank %, Dense %, BM25 %)
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
