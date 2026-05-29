# RAG Tuning & Optimization — Practical Guide

> Quick reference for improving RAG performance  
> **Last Updated**: May 29, 2026

---

## Quick Tuning Checklist

```
□ Have you run python main.py --stats?
□ Do you have test queries ready?
□ Have you tried the defaults first?
□ Are you changing one variable at a time?
□ Are you measuring results objectively?
```

---

## Scenario 1: Results are Too Generic / Broad

**Symptoms**: Query "laptop bids" returns furniture, office supplies, etc.

**Solutions (in order of impact)**:

### Step 1: Increase Semantic Weight
```python
# File: rag/vector_store.py, line ~158
# BEFORE:
hybrid_score = (semantic_score * 0.6) + (keyword_score * 0.4)

# AFTER:
hybrid_score = (semantic_score * 0.8) + (keyword_score * 0.2)

# Effect: Prioritizes semantic matching over exact keyword match
# Use when: Your queries are about intent/meaning, not exact keywords
```

### Step 2: Add Field Weighting
```python
# File: rag/vector_store.py, line ~105
# BEFORE (default):
fields_text = {
    "full_item_name": 3.0,
    "department": 1.5,
    "bid_type": 1.0,
    "product_type": 1.0,
}

# AFTER (stricter matching):
fields_text = {
    "full_item_name": 5.0,    # ← Much stricter
    "department": 1.5,
    "bid_type": 1.0,
    "product_type": 1.0,
}

# Effect: Exact item name match becomes critical
# Keyword score drops if query not found in item names
```

### Step 3: Use Filters
```bash
# Instead of:
python main.py --ask "laptop bids"

# Try:
python main.py --ask "laptop" --filter product_type=Product

# Effect: Reduces search space before scoring
# Only searches Product type bids
```

### Step 4: Lower Top-K
```env
# In .env:
RAG_TOP_K=3  # Was 5

# Effect: Returns only best 3 matches (vs 5)
# Less noise, higher precision
```

**Full tuning config for "precision" mode**:
```env
# .env file
RAG_TOP_K=3
RAG_CHUNK_SIZE=600          # Tighter chunks
RAG_CHUNK_OVERLAP=50        # Less overlap

# vector_store.py line ~158:
hybrid_score = (semantic_score * 0.8) + (keyword_score * 0.2)

# vector_store.py line ~105:
fields_text = {
    "full_item_name": 5.0,
    "department": 1.5,
    "bid_type": 1.0,
    "product_type": 1.0,
}
```

---

## Scenario 2: Missing Relevant Results

**Symptoms**: Query "IT hardware" returns only exact matches, misses "computer", "server", "network equipment"

**Solutions (in order of impact)**:

### Step 1: Better Embedding Model
```env
# BEFORE:
RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2

# AFTER:
RAG_EMBEDDING_MODEL=all-mpnet-base-v2

# Effect: Better semantic understanding
# Drawback: 20x larger model, slower indexing
# MUST reindex: python main.py --reindex
```

### Step 2: Increase Semantic Weight
```python
# File: rag/vector_store.py, line ~158
# BEFORE:
hybrid_score = (semantic_score * 0.6) + (keyword_score * 0.4)

# AFTER:
hybrid_score = (semantic_score * 0.8) + (keyword_score * 0.2)

# Effect: Finds more synonyms and related concepts
```

### Step 3: Increase Top-K
```env
# BEFORE:
RAG_TOP_K=5

# AFTER:
RAG_TOP_K=15

# Effect: Returns more candidates
# May include more noise
```

### Step 4: Larger Chunks
```env
# BEFORE:
RAG_CHUNK_SIZE=800

# AFTER:
RAG_CHUNK_SIZE=1500

# Effect: Each chunk has more context
# Better for capturing multi-field relationships
# MUST reindex
```

**Full tuning config for "recall" mode**:
```env
# .env file
RAG_TOP_K=15
RAG_CHUNK_SIZE=1500
RAG_CHUNK_OVERLAP=200
RAG_EMBEDDING_MODEL=all-mpnet-base-v2

# vector_store.py line ~158:
hybrid_score = (semantic_score * 0.8) + (keyword_score * 0.2)

# vector_store.py line ~105:
fields_text = {
    "full_item_name": 2.0,    # ← Relax strict matching
    "department": 1.5,
    "bid_type": 1.0,
    "product_type": 1.0,
}
```

**Then reindex**:
```bash
python main.py --reindex
```

---

## Scenario 3: Wrong Bid Types in Results

**Symptoms**: Query "service contracts" returns Product bids instead of Service bids

**Solution**: Use keyword field weighting

```python
# File: rag/vector_store.py, line ~105
# BEFORE (default):
fields_text = {
    "full_item_name": 3.0,
    "department": 1.5,
    "bid_type": 1.0,          # ← bid_type has low weight
    "product_type": 1.0,
}

# AFTER (boost type matching):
fields_text = {
    "full_item_name": 3.0,
    "department": 1.5,
    "bid_type": 3.0,          # ← Increased from 1.0
    "product_type": 2.0,      # ← Increased from 1.0
}

# Effect: Exact bid_type/product_type match now critical
# "Service Bid/RAs" will match query for "service"
```

---

## Scenario 4: Slow Queries

**Symptoms**: Queries take 5-10 seconds to complete

**Root Cause Analysis**:

```bash
# Step 1: Is it embeddings, search, or LLM?
python main.py --ask "test query"  # Note total time

# If ~1-2 sec: Likely LLM generation
# If ~200-500ms: Likely vector search or embedding

# Step 2: Test without LLM
RAG_LLM_PROVIDER=""  # Disable LLM in .env
python main.py --ask "test query"  # Much faster?
```

### For Slow Embedding/Search:

**Solution A: Faster Embedding Model**
```env
# BEFORE:
RAG_EMBEDDING_MODEL=all-mpnet-base-v2

# AFTER (faster):
RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2

# Speed improvement: 50-70% faster
# Accuracy impact: Minor (still very good)
```

**Solution B: Reduce Chunk Size**
```env
# BEFORE:
RAG_CHUNK_SIZE=1500

# AFTER (faster):
RAG_CHUNK_SIZE=600

# Speed improvement: 30-40% faster indexing
# Search: Slightly less context per chunk
# MUST reindex
```

### For Slow LLM:

**Solution A: Faster LLM Model**
```env
# BEFORE:
OLLAMA_MODEL=llama3

# AFTER (faster):
OLLAMA_MODEL=tinyllama

# Speed improvement: 3-5x faster
# Quality: Slightly lower
```

**Solution B: Retrieval-Only Mode**
```env
# BEFORE:
RAG_LLM_PROVIDER=ollama

# AFTER (instant):
RAG_LLM_PROVIDER=""

# Speed improvement: 10x faster (no LLM call)
# Output: Structured bid list (no natural language answer)
```

**Solution C: Reduce Retrieved Bids**
```env
# BEFORE:
RAG_TOP_K=15

# AFTER:
RAG_TOP_K=5

# Effect: LLM processes fewer bids
# If LLM is bottleneck: ~3x faster
```

**Full speed-optimized config**:
```env
RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2
RAG_CHUNK_SIZE=600
RAG_CHUNK_OVERLAP=50
RAG_TOP_K=5
RAG_LLM_PROVIDER=""
```

---

## Scenario 5: Results from Wrong Department

**Symptoms**: Query "IT laptops" returns General Services laptops, not IT department

**Solution: Combine weights + filters**

### Option A: Adjust Field Weights (keyword matching)
```python
# File: rag/vector_store.py, line ~105
fields_text = {
    "full_item_name": 3.0,
    "department": 2.5,        # ← Increased from 1.5 (more important)
    "bid_type": 1.0,
    "product_type": 1.0,
}

# Effect: Department name match now heavily weighted
```

### Option B: Use Filters (explicit)
```bash
# BEFORE:
python main.py --ask "IT department laptops"

# AFTER (explicit filter):
python main.py --ask "laptops" --filter department=IT

# Effect: Only searches IT department bids
# Fastest & most reliable approach
```

---

## Scenario 6: LLM Returns Fabricated Information

**Symptoms**: LLM includes data not in the original bids

**Solution: Check System Prompt**

```python
# File: rag/llm.py

SYSTEM_PROMPT = """You are a GeM bid assistant.
Answer ONLY using the structured bid data in RETRIEVED BID CONTEXT.

...

- Never hallucinate values not in the context.
"""

# Ensure this includes:
# ✓ "ONLY using"
# ✓ "Never hallucinate"
# ✓ Specific format requirements
```

**If still happening**:

### Option 1: Different LLM Model
```env
OLLAMA_MODEL=mistral    # More factual than llama3
```

### Option 2: Lower LLM Temperature
```python
# File: rag/llm.py, line ~125
options = {
    "temperature": 0.0,     # Already at minimum
    "num_predict": 1024,
    "num_ctx": 4096,
}

# temperature=0.0 is already most deterministic
# If still hallucinating: Model quality issue
```

### Option 3: Retrieval-Only Mode
```env
RAG_LLM_PROVIDER=""

# Effect: Returns structured list instead of LLM answer
# No hallucination possible (only shows retrieved data)
```

---

## Scenario 7: Same Bid Appears Multiple Times in Results

**Symptoms**: Query returns "GEM/2024/B/123" as result #1, #3, #5

**Cause**: Deduplication not working or index corrupted

**Solution**:

```bash
# Check current index health:
python main.py --stats

# Note: "Vector store chunks" vs "SQLite total bids"
# Ratio should be 3-5:1
# If ratio > 10:1 or < 1:1: Rebuild

python main.py --reindex
```

**After reindex, verify**:
```bash
# Query and check for duplicates:
python main.py --ask "any bid"

# Should see:
# GEM/2024/B/123 : Score 0.95
# (not repeated)
```

---

## Configuration Template: Different Use Cases

### Template 1: "Perfect Precision" (E-commerce-like)
```env
RAG_TOP_K=3
RAG_CHUNK_SIZE=600
RAG_CHUNK_OVERLAP=50
RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2
RAG_LLM_PROVIDER=""
```

```python
# vector_store.py line ~158
hybrid_score = (semantic_score * 0.7) + (keyword_score * 0.3)

# vector_store.py line ~105
fields_text = {
    "full_item_name": 5.0,
    "department": 1.5,
    "bid_type": 1.0,
    "product_type": 1.0,
}
```

**Best for**: "Find me THIS exact item"

### Template 2: "High Recall" (Research-like)
```env
RAG_TOP_K=20
RAG_CHUNK_SIZE=1500
RAG_CHUNK_OVERLAP=300
RAG_EMBEDDING_MODEL=all-mpnet-base-v2
RAG_LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3
```

```python
# vector_store.py line ~158
hybrid_score = (semantic_score * 0.8) + (keyword_score * 0.2)

# vector_store.py line ~105
fields_text = {
    "full_item_name": 2.0,
    "department": 1.5,
    "bid_type": 1.0,
    "product_type": 1.0,
}
```

**Best for**: "Show me EVERYTHING related to this topic"

### Template 3: "Balanced Default" (Current)
```env
RAG_TOP_K=5
RAG_CHUNK_SIZE=800
RAG_CHUNK_OVERLAP=100
RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2
RAG_LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3
```

```python
# vector_store.py line ~158
hybrid_score = (semantic_score * 0.6) + (keyword_score * 0.4)

# vector_store.py line ~105
fields_text = {
    "full_item_name": 3.0,
    "department": 1.5,
    "bid_type": 1.0,
    "product_type": 1.0,
}
```

**Best for**: General-purpose queries

### Template 4: "Maximum Speed" (API serving)
```env
RAG_TOP_K=3
RAG_CHUNK_SIZE=400
RAG_CHUNK_OVERLAP=0
RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2
RAG_LLM_PROVIDER=""
```

```python
# vector_store.py line ~158
hybrid_score = (semantic_score * 0.7) + (keyword_score * 0.3)

# vector_store.py line ~105
fields_text = {
    "full_item_name": 4.0,
    "department": 1.0,
    "bid_type": 1.0,
    "product_type": 1.0,
}
```

**Best for**: Sub-100ms response requirements

---

## Testing Protocol

### Step 1: Create Test Suite
```
Create file: test_queries.txt

Test Case 1:
  Query: "IT hardware laptops"
  Expected: Dell, HP, Lenovo laptop bids
  Expected NOT: Furniture, stationery

Test Case 2:
  Query: "construction services"
  Expected: Civil works, labor, machinery rental
  Expected NOT: Product bids

... (create 5-10 test cases)
```

### Step 2: Baseline Measurement
```bash
# Reset to defaults:
# RAG_TOP_K=5
# RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2
# hybrid_score = (0.6 * semantic) + (0.4 * keyword)

python main.py --ask "IT hardware"

# Note results, score distribution
# Calculate success rate (how many correct?)
```

### Step 3: Make ONE Change
```bash
# Change only ONE variable:
# RAG_TOP_K=3  (was 5)

python main.py --ask "IT hardware"

# Compare results to baseline
# Did it improve?
```

### Step 4: Iterate
```bash
# If improved: Keep the change, try next variable
# If worsened: Revert, try different change

# Repeat until satisfied
```

### Step 5: Document Changes
```
Changes made:
1. RAG_TOP_K: 5 → 3      (removed noise)
2. Field weight: IT weight 3.0 (emphasize type matching)
3. hybrid score: 0.6/0.4 → 0.7/0.3 (semantic priority)

Results:
- Before: 3/5 test cases correct (60%)
- After: 5/5 test cases correct (100%)
- Speed: 250ms → 180ms (28% faster)
```

---

## Advanced: Custom Intent Detection

**File**: `rag/query_engine.py`, lines ~20-26

Add more patterns to detect query type:

```python
import re

# Existing patterns
_LIST_INTENT = re.compile(r"\b(all|every|list|...)\b", re.IGNORECASE)
_FOCUSED_INTENT = re.compile(r"\b(bid number|...)\b", re.IGNORECASE)

# NEW: Add budget intent
_BUDGET_INTENT = re.compile(
    r"\b(budget|price|cost|value|estimate|within|under|above)\s*(\d+|[A-Z]+)",
    re.IGNORECASE
)

# NEW: Add date intent
_DATE_INTENT = re.compile(
    r"\b(recent|new|latest|today|this week|this month|upcoming)\b",
    re.IGNORECASE
)

def _smart_top_k(question: str, default_k: int) -> int:
    if _LIST_INTENT.search(question):
        return max(default_k, 15)
    if _FOCUSED_INTENT.search(question):
        return max(1, default_k // 2)
    if _BUDGET_INTENT.search(question):
        return max(default_k, 10)  # Budget queries: get more options
    if _DATE_INTENT.search(question):
        return default_k  # Date queries: standard
    return default_k
```

This allows auto-tuning based on query patterns.

---

## Debugging Commands

```bash
# Show current stats
python main.py --stats

# Chat mode (interactive testing)
python main.py --chat

# Search-only (no LLM)
python main.py --ask "query" /search
# (In chat, use: /search query)

# With metadata filter
python main.py --ask "hardware" --filter product_type=Product

# Full reindex (slow but comprehensive)
python main.py --reindex

# One-time scrape (to add new bids)
python main.py --once
```

---

## Decision Tree: What to Change First?

```
START: Query returning wrong results?

├─ Too many irrelevant results?
│  ├─ Try: Increase semantic weight (0.6→0.7)
│  ├─ Try: Decrease top_k (5→3)
│  └─ Try: Add filter (--filter product_type=Product)
│
├─ Missing related results?
│  ├─ Try: Better embedding model (mpnet)
│  ├─ Try: Increase top_k (5→15)
│  └─ Try: Decrease semantic weight (0.6→0.5)
│
├─ Wrong type/department?
│  ├─ Try: Boost type field weight (1.0→3.0)
│  ├─ Try: Boost dept field weight (1.5→2.5)
│  └─ Try: Add explicit filter
│
├─ Too slow?
│  ├─ Try: Faster embedding model
│  ├─ Try: Smaller chunks (1500→800)
│  ├─ Try: Retrieval-only (no LLM)
│  └─ Try: Faster LLM model
│
└─ Duplicates in results?
   └─ Try: python main.py --reindex
```

---

## Performance Metrics to Track

```
Metric 1: Query Latency
  Good: < 500ms (retrieval-only)
  OK: 1-3 sec (with LLM)
  Poor: > 5 sec

Metric 2: Result Relevance
  Measure: % of top-5 results that match intent
  Good: > 80%
  OK: 60-80%
  Poor: < 60%

Metric 3: Index Health
  Measure: chunks:bids ratio
  Good: 3-5:1
  OK: 2-6:1
  Poor: < 2:1 or > 10:1 (reindex!)

Metric 4: Vector Store Size
  Monitor: Total chunks
  Should grow with scraped bids
  If plateaus: No new bids indexed?
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | May 2026 | Initial practical guide |

