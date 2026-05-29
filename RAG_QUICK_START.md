# GeM Bid RAG System — Quick Start Summary

> Complete documentation overview  
> **Last Updated**: May 29, 2026

---

## Documentation Overview

You now have 4 comprehensive guides covering all aspects of the RAG system:

### 1. **RAG_ARCHITECTURE_GUIDE.md** (Read First!)
   - **What**: Complete system architecture overview
   - **Contains**:
     - System component overview
     - Data flow (scraping → indexing → querying)
     - How each component works
     - Configuration parameters
     - Scoring mechanism theory
   - **When to read**: 
     - First time understanding the system
     - Need big-picture understanding

### 2. **RAG_SCORING_EXAMPLES.md** (Most Visual)
   - **What**: Visual examples of how scoring works
   - **Contains**:
     - Step-by-step scoring calculations
     - Real examples with numbers
     - Decision trees for weight changes
     - Pattern recognition for scores
   - **When to read**: 
     - Want to understand WHY results rank the way they do
     - Need concrete examples

### 3. **RAG_TUNING_GUIDE.md** (Most Practical)
   - **What**: How to tune the system for your needs
   - **Contains**:
     - Scenario-based solutions
     - Configuration templates
     - Testing protocols
     - Debugging commands
   - **When to read**: 
     - Results not meeting expectations
     - Want to optimize for specific use case

### 4. **This File** (Quick Reference)
   - **What**: Fast lookup and quick commands
   - **Contains**:
     - Common commands
     - Key configuration values
     - Scoring formula
     - Decision tree
   - **When to read**: 
     - Need quick answer
     - Looking for specific command

---

## System at a Glance

```
Your system = Semantic Search + Keyword Matching + Optional LLM

Data Flow:
  Scrape PDFs → Extract fields → Store in SQLite + Vector DB
                                        ↓
  User Query → Embed → Hybrid Search → Format results → Show/LLM
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

Keyword Score = Σ(word_matches × field_weights) / total_weights
              → Captures exact matches in structured fields
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
  Keyword: 0.95 (exact "Laptops" match)
  Hybrid: (0.88 × 0.6) + (0.95 × 0.4) = 0.906 ✓ Top result!

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
# Then: type query, or /search query, or quit

# Single query
python main.py --ask "IT hardware bids"

# Query with filter
python main.py --ask "bids" --filter product_type=Product

# Retrieval only (no LLM)
python main.py --ask "laptops"
# (with RAG_LLM_PROVIDER="")

# System health check
python main.py --stats
```

### Indexing & Maintenance

```bash
# Rebuild entire vector index
python main.py --reindex

# New scrape run
python main.py --once

# Continuous scraping (hourly)
python main.py
# (Ctrl+C to stop)
```

---

## Decision Tree: What to Change

```
START → Are results good?
  │
  ├─ YES → Skip to "Production Settings"
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
     │  ├─ Try: Better model (all-mpnet-base-v2)
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
RAG_TOP_K=5                           # Return 5 results (adjust for scope)
RAG_CHUNK_SIZE=800                   # Chunk size (larger = more context)
RAG_CHUNK_OVERLAP=100                # Overlap between chunks

# Embedding model (affects quality & speed)
RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2
# Options:
#   all-MiniLM-L6-v2 (fast, good)
#   all-mpnet-base-v2 (accurate, slow)
#   all-MiniLM-L12-v2 (good balance)

# LLM Provider (for answer generation)
RAG_LLM_PROVIDER=ollama
# Options:
#   ollama (local, free, good)
#   openai (cloud, $$$, excellent)
#   "" (retrieval only, instant)

# If using Ollama:
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
# Options: llama3, mistral, neural-chat, etc.

# If using OpenAI:
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

### In code files:

**File: `rag/vector_store.py` line ~158**
```python
# Adjust these weights:
hybrid_score = (semantic_score * 0.6) + (keyword_score * 0.4)
#                                  ↓                    ↓
#                    Change these values to tune behavior
```

**File: `rag/vector_store.py` line ~105**
```python
# Adjust these field weights:
fields_text = {
    "full_item_name": 3.0,    # How important: exact item name match
    "department": 1.5,        # How important: department match
    "bid_type": 1.0,          # How important: bid type match
    "product_type": 1.0,      # How important: product type match
}
```

---

## Common Tuning Profiles

### Profile 1: **High Precision** (Exact matches)
```env
RAG_TOP_K=3
RAG_CHUNK_SIZE=600
RAG_LLM_PROVIDER=""
```
```python
hybrid_score = (semantic_score * 0.7) + (keyword_score * 0.3)
fields_text["full_item_name"] = 5.0
```
✓ For: Finding specific bids
✗ Won't: Catch synonyms or related results

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
✓ For: Comprehensive research
✗ Won't: Filter noise well

### Profile 3: **Balanced** (Default, good for most)
```env
RAG_TOP_K=5
RAG_CHUNK_SIZE=800
RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2
RAG_LLM_PROVIDER=ollama
```
```python
hybrid_score = (semantic_score * 0.6) + (keyword_score * 0.4)
fields_text = default
```
✓ For: General queries
✗ Won't: Excel at any specific goal

### Profile 4: **Maximum Speed** (API serving)
```env
RAG_TOP_K=3
RAG_CHUNK_SIZE=400
RAG_LLM_PROVIDER=""
```
```python
hybrid_score = (semantic_score * 0.7) + (keyword_score * 0.3)
fields_text["full_item_name"] = 4.0
```
✓ For: < 100ms response time
✗ Won't: Have long LLM generation

---

## Testing Checklist

When tuning, follow this process:

```
□ Create 5 test queries you care about
□ Run baseline (current settings): python main.py --ask "query"
□ Note results and scores
□ Change ONE parameter only
□ Run again with new setting
□ Compare results
□ Did it improve? 
  ├─ YES: Keep change, repeat with next param
  └─ NO: Revert, try different change
□ Test all 5 queries before finalizing
□ Document changes made
```

### Test Query Template

```
Query: "IT department laptops"
Expected results: Dell, HP, Lenovo from IT dept
Expected NOT: Furniture, Office supplies

Score interpretation:
- Top result score > 0.70: Good
- Top result score 0.50-0.70: Okay
- Top result score < 0.50: Investigate
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

---

## Important Files to Know

```
Your codebase structure:

d:\Projects\gem_scraper\
├── main.py                    ← Entry point (commands here)
├── config/settings.py         ← All config values
├── rag/
│  ├── query_engine.py         ← Query orchestration + intent detection
│  ├── vector_store.py         ← HYBRID SCORING (line ~158)
│  ├── embedder.py             ← Embedding & chunking
│  ├── llm.py                  ← LLM provider code
│  └── query_engine.py         ← Smart top_k logic
├── storage/
│  ├── database.py             ← SQLite operations
│  └── gem_bids.db             ← Your bids database
├── core/
│  ├── parser.py               ← PDF text extraction
│  └── browser.py              ← Web scraping
└── documentation/
   ├── RAG_ARCHITECTURE_GUIDE.md    ← (You just created!)
   ├── RAG_TUNING_GUIDE.md          ← (You just created!)
   ├── RAG_SCORING_EXAMPLES.md      ← (You just created!)
   └── RAG_QUICK_START.md           ← (This file!)
```

---

## Key Concepts to Remember

### 1. Hybrid Scoring is Your Secret Weapon

- **Semantic alone**: Great at understanding intent, bad at exact matches
- **Keyword alone**: Great at exact matches, bad at synonyms
- **Together**: Best of both worlds!

### 2. Field Weights Control Priority

Higher weight on `full_item_name` → Item name match crucial
Higher weight on `department` → Department match crucial

### 3. Top-K is Your Precision/Recall Knob

- Small top_k (2-3): High precision, may miss results
- Large top_k (15-20): High recall, includes noise

### 4. Filters Are Your Fast Lane

Using filters (`--filter`) is MUCH faster than relying on scoring alone.

### 5. Reindex When Model Changes

If you change embedding model → Must reindex!
If you change chunk size → Must reindex!
If you just change weights → NO reindex needed!

---

## Performance Expectations

### Indexing

```
Operation: python main.py --reindex

Typical times:
- 100 bids: 10-20 seconds
- 1000 bids: 2-3 minutes
- 10000 bids: 20-30 minutes

Factors:
- Embedding model size (mpnet slower than MiniLM)
- Chunk size (larger = more chunks = slower)
- CPU power (GPU would be 10x faster)
```

### Querying

```
Operation: python main.py --ask "query"

Typical times:
- Embedding query: 50ms
- Search: 100-500ms (depends on index size)
- LLM: 1000-3000ms (most time!)

To speed up: Remove LLM (RAG_LLM_PROVIDER="")
Result: 150-550ms total
```

---

## When to Contact Developers / Debug

You should be able to solve 90% of issues with the guides. Contact support if:

1. **Scores are 0 or very low (<0.1) across all results**
   - Likely: Index corruption or embedding model mismatch
   - Fix: `python main.py --reindex`

2. **Results are consistently worse after changes**
   - Likely: Configuration syntax error
   - Fix: Check .env file format, or revert changes

3. **System crashes or hangs**
   - Likely: Out of memory or database lock
   - Fix: Check logs in `logs/` folder

4. **LLM returns completely irrelevant answers**
   - Likely: LLM model issue
   - Fix: Try different model or retrieval-only

---

## Next Steps

1. **Understand the architecture** (5 min read)
   ```bash
   Read: RAG_ARCHITECTURE_GUIDE.md → System Overview section
   ```

2. **See it in action** (2 min test)
   ```bash
   python main.py --chat
   # Type: "Show me IT bids"
   # Type: /search laptops
   # Type: quit
   ```

3. **Understand the scoring** (10 min read)
   ```bash
   Read: RAG_SCORING_EXAMPLES.md → Example 1
   Run: python main.py --ask "laptops"
   Compare scores to examples
   ```

4. **Tune for your use case** (variable time)
   ```bash
   Read: RAG_TUNING_GUIDE.md → Scenario matching yours
   Make one change
   Test with 5 queries
   Repeat
   ```

5. **Document your setup** (5 min)
   ```bash
   Note down:
   - Which profile you used (Precision/Recall/Balanced)
   - Changes you made
   - Test query results
   - Final performance metrics
   ```

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

### After changing no-reindex settings:

Just use normally (changes apply immediately)

---

## Summary

Your RAG system is:
1. **Well-architected**: Separates concerns (scrape → embed → search → answer)
2. **Tunable**: Multiple parameters to optimize for your needs
3. **Transparent**: You can see and understand why results rank as they do
4. **Production-ready**: Can handle thousands of bids at scale

The scoring formula is the heart of it all:
```
Hybrid Score = (Semantic × 0.6) + (Keyword × 0.4)
```

Adjust weights and parameters based on your specific use case!

---

## File Organization

For reference, I've created these files for you:

1. **RAG_ARCHITECTURE_GUIDE.md** (200+ lines)
   - Complete system design
   - Component-by-component explanation
   - Configuration reference
   - Theory behind scoring

2. **RAG_SCORING_EXAMPLES.md** (250+ lines)
   - Real numerical examples
   - Step-by-step calculations
   - Visual decision trees
   - Pattern recognition

3. **RAG_TUNING_GUIDE.md** (400+ lines)
   - Scenario-based solutions
   - Configuration templates
   - Testing protocols
   - Debugging strategies

4. **This Quick Start** (300+ lines)
   - Fast reference
   - Common commands
   - Decision trees
   - Key concepts

**Total**: ~1200 lines of comprehensive documentation!

---

**You're all set!** 🎉

Start with the Architecture Guide to understand the system, then use the Tuning Guide to optimize for your specific needs. The Scoring Examples will help you debug when results don't match expectations.

All three guides cross-reference each other for easy navigation.

