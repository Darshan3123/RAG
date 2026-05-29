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

- **Data Collection**: Web scraping of bid PDFs from GeM website
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
│    Downloads PDFs                    Stores bid metadata    │
│                                      in SQLite              │
│                                             ↓               │
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
   ├─ Fetches active bids only
   ├─ Downloads PDF documents
   └─ Extracts raw text

2. PARSER (core/parser.py)
   ├─ Extracts structured fields from PDF text
   ├─ Fields extracted:
   │  ├─ bid_no (GEM/2024/B/12345)
   │  ├─ bid_type (Product Bid/RAs, Service Bid/RAs, etc.)
   │  ├─ full_item_name (What is being bid on)
   │  ├─ department (Government dept)
   │  ├─ quantity
   │  ├─ start_date, end_date
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

2. SMART TOP_K SELECTION (query_engine.py)
   ├─ Detects query intent:
   │  ├─ Listing intent (all, every, list, show) → top_k = 15
   │  ├─ Focused lookup (specific bid, find bid) → top_k = k/2
   │  └─ Generic → top_k = default (5)
   └─ Ensures better results for different query types

3. VECTOR SEARCH (vector_store.py)
   ├─ Embed query using same model
   ├─ Fetch top_k*4 raw chunks from ChromaDB
   │  (over-fetch to account for deduplication)
   ├─ For each chunk, calculate:
   │  ├─ Semantic score: cosine similarity (0-1)
   │  └─ Keyword score: TF-IDF style matching
   ├─ Combine: hybrid_score = (semantic * 0.6) + (keyword * 0.4)
   ├─ Deduplicate by bid_no (keep highest score)
   └─ Sort by hybrid score, return top_k

4. LLM INTEGRATION (llm.py)
   ├─ If RAG_LLM_PROVIDER = "openai" or "ollama"
   │  ├─ Format retrieved bids into structured prompt
   │  ├─ Send to LLM with system instructions
   │  ├─ LLM formats response with exact template
   │  └─ Return formatted answer
   └─ If no LLM provider: return retrieval-only results

5. OUTPUT
   ├─ Sources: List of retrieved bids with:
   │  ├─ bid_no, department, full_item_name
   │  ├─ end_date, estimated_value
   │  ├─ relevance_score (hybrid score)
   │  └─ document_url
   └─ Answer: LLM-generated or retrieval-only
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

**Purpose**: Store bid embeddings and perform similarity search.

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

#### b) **Search (Hybrid)**

The search function performs **hybrid scoring** combining:

1. **Semantic Score** (60% weight):
   - Cosine similarity between query embedding and chunk embeddings
   - Range: 0 to 1 (1 = perfect match)
   - Formula: `1 - cosine_distance`

2. **Keyword Score** (40% weight):
   - TF-IDF style matching on structured fields
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

#### a) **Smart Top-K Selection**
```python
_smart_top_k(question):
    if question contains listing intent words:
        (all, every, list, show all, how many, etc.)
        → return max(default_k, 15)
    
    elif question contains focused lookup words:
        (bid number, specific, find bid, etc.)
        → return max(1, default_k // 2)
    
    else:
        → return default_k
```

#### b) **Ask Function**
```python
ask(question, filters=None, top_k=None):
    1. Determine top_k using smart selection
    2. Call search() with query + filters + top_k
    3. If no results → return "No relevant bids found"
    4. Call LLM with results (if configured)
    5. Extract sources with:
       - bid_no, bid_type, product_type
       - full_item_name (cleaned)
       - department, end_date, estimated_value
       - document_url
       - relevance_score (the hybrid score)
    6. Return structured response
```

#### c) **Search-Only Function**
```python
search_only(query, filters=None, top_k=None):
    - Similar to ask() but without LLM
    - Just returns raw retrieval results
    - Useful for /search command in chat
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
   - Returns formatted retrieval results
   - Always works, no dependencies

**Flow**:

```python
call_llm(question, chunks):
    1. build_prompt(question, chunks)
       - Formats chunks into structured blocks
       - Includes system instructions
       - Max 8 bids per prompt (configurable)
    
    2. Call appropriate provider:
       - OpenAI: Uses chat completions API
       - Ollama: Uses HTTP /api/generate endpoint
       - Fallback: Parse prompt as table
    
    3. Return LLM response or fallback
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

#### Step 3: Keyword Scoring
```
For each bid metadata:
    1. Extract query keywords (remove stop words)
       Query: "laptop bids"
       Keywords: {"laptop", "bids"}
       (Removed: "show", "me")
    
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

**Examples**:

```
Scenario 1: Detailed technical specs spread across pages
  → Increase CHUNK_SIZE to 1200, CHUNK_OVERLAP to 200
     Reason: Keeps complete info in one chunk

Scenario 2: Bid metadata is concise and well-structured
  → Decrease CHUNK_SIZE to 500, CHUNK_OVERLAP to 50
     Reason: Each chunk captures complete info
```

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

**When to change**:
- Current model too slow? → Use `all-MiniLM-L6-v2` (even faster)
- Results not accurate enough? → Try `all-mpnet-base-v2` (more accurate)
- Need multi-language? → Use `paraphrase-multilingual-*`

**Important**: Changing this requires rebuilding the index!
```bash
python main.py --reindex
```

### 3. Search Settings

```env
# Number of top results to return
RAG_TOP_K=5

# Smart top_k adjustments:
# - Listing intent:     max(top_k, 15)
# - Focused lookup:     max(1, top_k // 2)
# - Default:            top_k
```

**When to tune**:

```env
RAG_TOP_K=3       # Returns fewer, higher-quality results
                  # Use when: precision > recall

RAG_TOP_K=10      # Returns more results (may include noise)
                  # Use when: recall > precision, comprehensive listing
```

### 4. Hybrid Scoring Weights

**File**: `rag/vector_store.py` line ~90

Current:
```python
hybrid_score = (semantic_score * 0.6) + (keyword_score * 0.4)
```

**To adjust weights**:

```python
# Make keyword matching more important (e.g., exact department must match)
hybrid_score = (semantic_score * 0.5) + (keyword_score * 0.5)

# Make semantic matching more important (e.g., intent over exact words)
hybrid_score = (semantic_score * 0.7) + (keyword_score * 0.3)
```

**When to adjust**:

| Scenario | Change | Reason |
|----------|--------|--------|
| Too many irrelevant results | 0.6→0.7 semantic, 0.4→0.3 keyword | Semantic similarity isn't enough; need exact matches |
| Missing relevant results | 0.6→0.5 semantic, 0.4→0.5 keyword | Keyword matching could find results semantic misses |
| Different departments in results | 0.6 semantic, 0.4→0.5 keyword | Boost keyword to enforce department filtering |
| Too narrow/specific results | 0.6→0.7 semantic, 0.4→0.3 keyword | Let semantic similarity find broader matches |

### 5. Keyword Field Weights

**File**: `rag/vector_store.py` line ~105

```python
fields_text = {
    "full_item_name": 3.0,    # Match item name heavily
    "department": 1.5,
    "bid_type": 1.0,
    "product_type": 1.0,
}
```

**When to adjust**:

```python
# Example: Make department matching more important
fields_text = {
    "full_item_name": 3.0,
    "department": 2.5,        # ← Increased from 1.5
    "bid_type": 1.0,
    "product_type": 1.0,
}

# Use case: Queries like "IT department bids"
#          Should strongly prefer IT department matches
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

| Provider | Setup | Cost | Speed | Quality | Customization |
|----------|-------|------|-------|---------|---------------|
| **ollama** | Install locally | Free | Medium | Good | Full control |
| **openai** | API key | $$ | Fast | Excellent | Limited |
| **None** | N/A | Free | Fast | N/A | N/A (retrieval-only) |

### 7. Query Time Settings (query_engine.py)

Smart top_k adjustment patterns (lines ~20-26):

```python
# Broad listing queries get higher top_k
_LIST_INTENT = re.compile(
    r"\b(all|every|list|show all|how many|complete list|"
    r"give me all|show me|display all|what bids|which bids)\b",
    re.IGNORECASE,
)
→ Increases top_k to 15 (get comprehensive results)

# Focused queries get lower top_k
_FOCUSED_INTENT = re.compile(
    r"\b(bid number|bid no|GEM/\d{4}|specific|"
    r"one bid|find bid|this bid)\b",
    re.IGNORECASE,
)
→ Decreases top_k to k//2 (get only most relevant)
```

**To customize intent detection**:

```python
# Add patterns for your specific use cases

# Example: If you see pattern "budget X"
r"\b(budget|value|price|cost|estimate)\b"
→ Could trigger higher keyword weight or different top_k

# Example: If you see "recent bids"
r"\b(recent|new|latest|today|this week)\b"
→ Could add date-based filtering
```

---

## Performance Optimization

### 1. Indexing Performance

**Bottle**: Embedding generation (can be slow for large PDFs)

**Optimizations**:

```python
# Use batch processing (already done in code)
embeddings = model.encode(
    texts,
    batch_size=32,        # Process 32 chunks at once
    show_progress_bar=False,
    normalize_embeddings=True,  # Cosine-ready
)

# To speed up further:
batch_size=64          # Larger batches (if memory allows)

# On GPU machines:
# - Move model to GPU automatically
# - 10x+ speedup possible
```

**Specific tuning**:

```env
# Smaller embedding model = faster indexing
RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2  # Fast
# vs
RAG_EMBEDDING_MODEL=all-mpnet-base-v2  # Accurate but slower
```

### 2. Search Performance

**Bottle**: ChromaDB query (usually fast, but can be slow with huge datasets)

**Optimizations**:

```python
# Current code already optimizes:
fetch_n = min(top_k * 4, total)  # Limit raw fetch to account for dedup

# For very large datasets (>100k bids):
fetch_n = min(top_k * 2, total)  # Reduce fetch (faster, less dedup)
```

### 3. Query Time Caching

**Add caching for repeated queries**:

```python
from functools import lru_cache

@lru_cache(maxsize=100)
def search_cached(query: str, top_k: int = 5):
    return search(query, top_k=top_k)

# Benefits:
# - Exact repeats return instant results
# - Memory: ~100 queries cached
# - Trade-off: Stale results if data changes frequently
```

### 4. Filtering Performance

**Using filters reduces search space**:

```python
# Slow: Search all ~50k chunks
results = engine.ask("IT bids")

# Fast: Search only IT department chunks
results = engine.ask(
    "IT bids",
    filters={"department": "IT Department"}
)

# Why faster: ChromaDB applies filter before similarity search
# Result set: 50k → 5k → top_k (much faster)
```

**In main.py**:
```bash
python main.py --ask "bids" --filter department=IT
```

---

## Troubleshooting & Best Practices

### Common Issues & Solutions

#### Issue 1: "Vector store is empty"

**Cause**: No bids indexed yet

**Solution**:
```bash
# Rebuild index from existing SQLite bids
python main.py --reindex

# Or: Run full scrape first
python main.py --once
```

#### Issue 2: Results are irrelevant or too narrow

**Root Cause Analysis**:

```
Likely causes:
1. Hybrid weights too biased toward keyword (set 0.4→0.3)
   → Try: hybrid_score = (semantic * 0.7) + (keyword * 0.3)

2. top_k too small (only looking at 1-2 results)
   → Try: RAG_TOP_K=10

3. Embedding model too generic
   → Try: all-mpnet-base-v2 (better quality)

4. Query is too specific/ambiguous
   → Try: Broaden query ("IT hardware" → "IT equipment")
```

**Debugging steps**:
```bash
# 1. See raw search results (no LLM)
python main.py --ask "your query" | grep "Overall Score"

# 2. Check score breakdown
# Scores should be 0.3-0.9 range
# If all 0.1-0.2: embedding model mismatch or wrong query

# 3. Try simpler query
python main.py --ask "laptops"
```

#### Issue 3: Same bid appears multiple times

**Cause**: Overlap causes multiple chunks per bid, code should deduplicate but bug possible

**Check**:
```bash
python main.py --stats
# Note: "Vector store chunks" should be larger than unique bids
# Ratio 3-5:1 is normal
```

**Solution**:
```bash
# Rebuild entire index
python main.py --reindex
```

#### Issue 4: Query returns results in wrong order

**Cause**: Hybrid scoring not matching your intent

**Solutions**:

Option A: Adjust hybrid weights
```python
# File: rag/vector_store.py, line ~158
# Change from (0.6, 0.4) to (0.7, 0.3)
hybrid_score = (semantic_score * 0.7) + (keyword_score * 0.3)
# Reload: python main.py --ask "your query"
```

Option B: Use filters
```bash
python main.py --ask "bids" --filter product_type=Product
# Reduces noise from other product types
```

Option C: Adjust keyword field weights
```python
# File: rag/vector_store.py, line ~105
fields_text = {
    "full_item_name": 4.0,    # ← Increase if item name match most important
    "department": 1.5,
    "bid_type": 1.0,
    "product_type": 1.0,
}
```

#### Issue 5: LLM returns hallucinated information

**Cause**: LLM going beyond retrieved context

**Solution**:

Check `SYSTEM_PROMPT` in `rag/llm.py`:
```python
# Should include:
"Answer ONLY using the structured bid data in RETRIEVED BID CONTEXT."
"Never hallucinate values not in the context."
```

If still happening:
- Try different LLM model: `OLLAMA_MODEL=mistral` (more precise)
- Switch to `RAG_LLM_PROVIDER=""` (retrieval-only, no hallucination)

#### Issue 6: Slow searches

**Root Cause Analysis**:

```
Timing breakdown:
1. Embed query: ~50ms
2. ChromaDB search: ~100-500ms (depends on index size)
3. LLM call: 1000-3000ms (most time!)

If slow: Usually LLM provider (network, model size)
```

**Solutions**:

```env
# Option 1: Faster LLM provider
OLLAMA_MODEL=tinyllama     # Smaller, faster

# Option 2: No LLM (instant results)
RAG_LLM_PROVIDER=""

# Option 3: Faster server (add timeout)
# Already in code: timeout=90 for Ollama
```

---

### Best Practices

#### 1. Query Phrasing

```
Good queries:
  "Show me IT hardware bids"
  (Clear intent + keywords)

Better queries:
  "List all product bids from IT department"
  (Specifies type + uses keywords)

Best queries with filters:
  python main.py --ask "bids" --filter product_type=Product
  (Explicit filter + clear query)

Avoid:
  "bids"                  (Too generic)
  "show me everything"    (Too broad)
  "gXfQw"                 (Garbage)
```

#### 2. Monitoring Quality

```bash
# Regular health checks:
python main.py --stats

# Monitor these metrics:
# - Vector store chunks: Should grow with scraped bids
# - Total SQLite bids: Should increase daily
# - Ratio chunks:bids: Should be 3-5:1

# If ratio > 10:1: Consider reindex
# If ratio < 1:1: Data corruption, reindex
```

#### 3. Tuning Process

Recommended tuning sequence:

```
1. Try defaults (usually good for 80% of queries)
   python main.py --ask "your test query"

2. If results are narrow/irrelevant:
   a. Increase top_k: RAG_TOP_K=10
   b. Decrease semantic weight: 0.6→0.5
   c. Increase keyword weight: 0.4→0.5

3. If results are too broad:
   a. Decrease top_k: RAG_TOP_K=3
   b. Increase semantic weight: 0.6→0.7
   c. Decrease keyword weight: 0.4→0.3

4. If LLM results worse than retrieval:
   a. Check SYSTEM_PROMPT in llm.py
   b. Try different LLM model
   c. Use retrieval-only mode

5. Monitor with multiple test queries before deploying
```

#### 4. Re-indexing Strategy

When to reindex:

```
✓ DO reindex when:
  - Changing RAG_EMBEDDING_MODEL
  - Changing RAG_CHUNK_SIZE / RAG_CHUNK_OVERLAP
  - Noticed data corruption
  - After major DB changes

✗ DON'T reindex when:
  - Just changing top_k, weights, LLM settings
  - Just updating filters
  - Scraping new bids (automatic)
```

Command:
```bash
python main.py --reindex
# Takes time proportional to # of bids
# (2-3 min for 1000 bids on CPU)
```

#### 5. Production Deployment

```yaml
recommended_settings.env:
  RAG_EMBEDDING_MODEL: all-MiniLM-L6-v2  # Fast, reliable
  RAG_TOP_K: 5                           # Balance coverage
  RAG_CHUNK_SIZE: 800                    # Standard
  RAG_CHUNK_OVERLAP: 100                 # Standard
  
  RAG_LLM_PROVIDER: ollama               # Local (no API cost)
  OLLAMA_MODEL: llama3                   # Reliable
  OLLAMA_BASE_URL: http://localhost:11434
  
  # Or use retrieval-only (most reliable):
  RAG_LLM_PROVIDER: ""
```

---

## Summary Table: When to Change What

| Goal | Parameter | Change | Impact |
|------|-----------|--------|--------|
| **Faster indexing** | RAG_CHUNK_SIZE | 800→600 | 20% faster, less context |
| **Faster indexing** | RAG_EMBEDDING_MODEL | mpnet→MiniLM | 50% faster, slightly lower accuracy |
| **More results** | RAG_TOP_K | 5→15 | More comprehensive, more noise |
| **Fewer results** | RAG_TOP_K | 5→2 | Higher quality, may miss relevant |
| **Better accuracy** | RAG_EMBEDDING_MODEL | MiniLM→mpnet | 30% slower, better quality |
| **Exact keyword match** | 0.6 semantic, 0.4 keyword | 0.5, 0.5 | More balanced, less semantic |
| **Intent-based search** | 0.6 semantic, 0.4 keyword | 0.7, 0.3 | Better for variations, less exact |
| **Faster queries** | RAG_LLM_PROVIDER | ollama→"" | Instant retrieval, no answers |
| **Better answers** | OLLAMA_MODEL | tinyllama→llama3 | 2-3x slower but better quality |

---

## Next Steps for Your System

1. **Test with sample queries**:
   ```bash
   python main.py --ask "IT department laptops"
   python main.py --ask "show all product bids" --filter product_type=Product
   python main.py --chat  # Interactive mode
   ```

2. **Monitor metrics**:
   ```bash
   python main.py --stats  # Check health
   ```

3. **Tune for your use case**:
   - Start with 3-5 test queries
   - Adjust weights based on results
   - Measure improvements

4. **Document changes**:
   - Keep notes of what you changed and why
   - Build testing suite of queries

---

**Document Version**: 1.0  
**Last Updated**: May 29, 2026  
**Author**: System Analysis  
