# GeM Bid Scraper — RAG Architecture & Tuning Guide

> **Last Updated:** May 2026  
> **Scope:** Complete RAG system architecture, scoring mechanism, and optimization strategies

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Data Flow Pipeline](#data-flow-pipeline)
3. [RAG Architecture](#rag-architecture)
4. [Scoring Mechanism (Hybrid Scoring)](#scoring-mechanism-hybrid-scoring)
5. [Configuration & Tuning](#configuration--tuning)
6. [Performance Optimization](#performance-optimization)
7. [Troubleshooting & Best Practices](#troubleshooting--best-practices)

---

## System Overview

Your system is a **Retrieval Augmented Generation (RAG)** pipeline for GeM (Government e-Marketplace) bid information. It combines:

- **Data Collection**: Web scraping of bid PDFs from GeM website (active bids only)
- **Card-Based Date Extraction**: Dates scraped from listing card HTML for accuracy
- **Vector Embeddings**: Converting bid text to high-dimensional vectors for similarity search
- **Hybrid Search**: Combining semantic similarity + keyword matching
- **LLM Integration**: Optional AI-powered answer generation (OpenAI or Ollama)
- **SQLite + ChromaDB**: Persistent storage of bids and embeddings

### Key Components:

```
┌─────────────────────────────────────────────────────────────┐
│                    ENTRY POINT: main.py                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────────┐  │
│  │  Scraper    │──→│  Parser      │──→│  Database        │  │
│  │ (browser.py)│   │(parser.py)   │   │(database.py)     │  │
│  └─────────────┘   └──────────────┘   └──────────────────┘  │
│         ↓                                        ↓          │
│  Downloads PDFs                    Stores bid metadata      │
│  Filters active bids               in SQLite                │
│  Scrapes dates from cards                   ↓               │
│                                    ┌─────────────────────┐  │
│                                    │  RAG Pipeline       │  │
│                                    ├─────────────────────┤  │
│  ┌──────────────────────────────── │ • Embedder          │ │
│  │                                 │ • Vector Store      │ │
│  │ Extracts text from PDFs         │ • Query Engine      │ │
│  │ Chunks into overlapping         │ • LLM Integration   │ │
│  │ windows                         └─────────────────────┘ │
│  │ Converts to embeddings              ↓                   │
│  │ Stores in ChromaDB             ChromaDB (vectors)       │
│  │                                                          │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│         Query Flow:                                          │
│  User Question → Embedding → Hybrid Search → LLM → Answer  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Data Flow Pipeline

### Phase 1: Scraping & Ingestion

```
1. SCRAPER (pipeline/scraper.py)
   ├─ Filters by bid type (Product, Service, etc.)
   ├─ Applies "Ongoing Bids/RA" filter → active bids only
   ├─ Downloads PDF documents
   ├─ Scrapes start_date + end_date from card HTML (accurate)
   └─ Extracts raw text from PDFs

2. PARSER (core/parser.py)
   ├─ get_dates_from_card(): Scrapes dates from listing card HTML
   │  ├─ Matches "Start Date: DD-MM-YYYY HH:MM AM/PM"
   │  ├─ Matches "End Date: DD-MM-YYYY HH:MM AM/PM"
   │  └─ Converts to 24-hour format via _to_24h()
   ├─ extract_pdf_text(): Extracts text via PyMuPDF (OCR fallback)
   ├─ parse_bid_data(): Extracts structured fields from PDF text
   │  ├─ bid_no (GEM/2024/B/12345)
   │  ├─ bid_type (Product Bid/RAs, Service Bid/RAs, etc.)
   │  ├─ full_item_name (What is being bid on)
   │  ├─ department (Government dept)
   │  ├─ quantity
   │  ├─ start_date, end_date (PDF fallback only)
   │  ├─ estimated_value
   │  ├─ bid_packet_type (Single/Two packet)
   │  └─ full_pdf_text (entire PDF content)
   └─ Uses regex patterns + fallback to OCR if needed

3. DATABASE (storage/database.py)
   ├─ Deduplicates using document_url as primary key
   ├─ Marks new bids vs. already-seen
   ├─ Stores in SQLite: storage/gem_bids.db
   └─ Logs all runs to run_log table

4. RAG INDEXING (rag/vector_store.py)
   ├─ For EACH new bid:
   │  ├─ build_bid_document(): Creates rich text
   │  │  └─ Combines: structured fields + PDF body
   │  ├─ chunk_text(): Splits into overlapping chunks
   │  ├─ embed_texts(): Converts to vectors
   │  └─ upsert_bid(): Stores in ChromaDB
   └─ Result: Searchable vector database
```

### Phase 2: Query Time

```
1. USER QUERY
   ├─ Question: "Show me all IT hardware bids"
   ├─ Optional filter: f:product_type=Product
   └─ Optional top_k override

2. EXIT DETECTION (query_engine.py) — checked FIRST
   ├─ Checked before any query processing
   ├─ Exit words: quit, exit, q, bye, goodbye, stop, close, end, done, ok bye
   └─ If matched → exit immediately (no query made)

3. SMART TOP_K SELECTION (query_engine.py)
   ├─ Detects query intent:
   │  ├─ Listing intent (all, every, list, show, how many, what bids, etc.)
   │  │  → top_k = max(default, 15)
   │  ├─ Focused lookup (specific bid, find bid, bid number, GEM/YYYY)
   │  │  → top_k = max(1, default // 2)
   │  └─ Generic → top_k = default (5)
   └─ Ensures better results for different query types

4. VECTOR SEARCH (vector_store.py)
   ├─ Embed query using same model
   ├─ Fetch top_k*4 raw chunks from ChromaDB
   │  (over-fetch to account for deduplication)
   ├─ For each chunk, calculate:
   │  ├─ Semantic score: cosine similarity (0-1)
   │  └─ Keyword score: TF-IDF style matching on structured fields
   ├─ Combine: hybrid_score = (semantic * 0.6) + (keyword * 0.4)
   ├─ Deduplicate by bid_no (keep highest score per bid)
   └─ Sort by hybrid score, return top_k

5. LLM INTEGRATION (llm.py)
   ├─ If RAG_LLM_PROVIDER = "openai" or "ollama"
   │  ├─ Format retrieved bids into structured prompt (max 8 bids)
   │  ├─ Send to LLM with system instructions
   │  ├─ LLM formats response with exact template
   │  └─ Return formatted answer
   └─ If no LLM provider: return retrieval-only results with score breakdown

6. OUTPUT
   ├─ Sources: List of retrieved bids with:
   │  ├─ bid_no, department, full_item_name
   │  ├─ end_date, estimated_value
   │  ├─ relevance_score (hybrid score)
   │  └─ document_url
   └─ Answer: LLM-generated or retrieval-only with score breakdown
```

---

## RAG Architecture

### 1. Embeddings (rag/embedder.py)

**Purpose**: Convert text into numerical vectors (embeddings) that capture semantic meaning.

**Model**: `all-MiniLM-L6-v2` (by default)
- Sentence-Transformers model
- 384-dimensional vectors
- Runs completely LOCAL (no API key needed)
- Fast & efficient for CPU

**Process**:

```python
1. build_bid_document(bid):
   - Creates a rich text document
   - Combines structured fields at the top (repeated for emphasis)
   - Followed by full PDF text
   - Result: Single text string with all bid info
   
   Example output:
   "Bid Number: GEM/2024/B/123 RA Number: GEM/2024/R/456 
    Bid Type: Product Bid/RAs Product Type: Product 
    Item: Industrial Machinery Quantity: 100 
    Department: Ministry of Tech ... [PDF body text]"

2. chunk_text(text):
   - Splits long documents into overlapping chunks
   - Chunk size: 800 characters (configurable)
   - Overlap: 100 characters (configurable)
   - Ensures context isn't lost at chunk boundaries
   - Keeps chunks ≥ 20 chars (filters out noise)
   
   Example:
   Text = "ABCDEFGHIJKLMNOP..." (2400 chars)
   Chunks:
   - [0:800]      = "ABCDEFGH...YZ"
   - [700:1500]   = "TUVWXYZ...ABC" (overlaps last 100)
   - [1400:2200]  = "XYZ...DEF"
   - [2100:2900]  = "...GHI"

3. embed_texts(texts):
   - Uses sentence-transformers to encode
   - Returns normalized embeddings (L2 norm = 1)
   - Enables cosine similarity directly
   - Batch size: 32 for efficiency
```

**Configuration**:
```env
# In .env file:
RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2    # Which model to use
RAG_CHUNK_SIZE=800                      # Characters per chunk
RAG_CHUNK_OVERLAP=100                   # Overlap between chunks
```

**Where embeddings are stored**: ChromaDB (`storage/chroma_db/`)

---

### 2. Vector Store (rag/vector_store.py)

**Purpose**: Store bid embeddings and perform hybrid similarity search.

**Technology**: ChromaDB (embedded vector database)
- Persistent storage in `storage/chroma_db/`
- Uses HNSW (Hierarchical Navigable Small World) algorithm
- Cosine similarity metric
- Supports metadata filtering

**Key Operations**:

#### a) **Upsert (Insert/Update)**

```python
upsert_bid(bid):
    1. Get or create ChromaDB collection
    2. Delete old chunks for this bid (if re-indexing)
    3. Build bid document (structured + PDF text)
    4. Chunk the text
    5. Embed all chunks
    6. Create metadata for each chunk
    7. Upsert to ChromaDB:
       - IDs: "{bid_no}__chunk_{i}"
       - Embeddings: 384-dim vectors
       - Documents: text chunks
       - Metadatas: bid fields (bid_no, department, etc.)
```

#### b) **Hybrid Search**

The search function performs **hybrid scoring** combining:

1. **Semantic Score** (60% weight):
   - Cosine similarity between query embedding and chunk embeddings
   - Range: 0 to 1 (1 = perfect match)
   - Formula: `1 - cosine_distance`

2. **Keyword Score** (40% weight) — `_keyword_score()`:
   - TF-IDF style matching on structured fields
   - Removes common stop words from query before matching
   - Matches query words against: item_name, department, bid_type, product_type
   - Field weights:
     - `full_item_name`: 3.0 (highest weight)
     - `department`: 1.5
     - `bid_type`: 1.0
     - `product_type`: 1.0
   - Range: 0 to 1

3. **Hybrid Score**:
   ```
   hybrid_score = (semantic_score × 0.6) + (keyword_score × 0.4)
   ```

**Example Scoring Breakdown**:
```
Query: "IT hardware laptops"

Bid 1: "Dell Laptops" (full_item_name)
  ├─ Semantic score: 0.87 (good embedding match)
  ├─ Keyword score: 0.95 (exact match for "laptops" in item_name)
  └─ Hybrid: (0.87 × 0.6) + (0.95 × 0.4) = 0.522 + 0.380 = 0.902

Bid 2: "Furniture for IT Department"
  ├─ Semantic score: 0.62 (weak embedding match)
  ├─ Keyword score: 0.50 (partial match for "IT")
  └─ Hybrid: (0.62 × 0.6) + (0.50 × 0.4) = 0.372 + 0.200 = 0.572

Result: Bid 1 (0.902) ranked before Bid 2 (0.572)
```

**Deduplication**:
- Raw chunks may contain the same bid multiple times (from overlap)
- Code keeps only the BEST scoring chunk per bid_no
- Returns top_k unique bids (not chunks)

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
