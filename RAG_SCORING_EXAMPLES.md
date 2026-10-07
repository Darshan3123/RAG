# RAG Scoring Deep Dive — Visual Guide

> **How exactly are scores calculated?** Step-by-step examples with real numbers  
> **Last Updated:** August 2026  
> **For:** Understanding the hybrid search and reranking pipeline through concrete examples

---

## The Scoring Flow

```
┌──────────────────────────────────────────┐
│ User Query: "Show me IT laptops"         │
└──────────────┬─────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ EXIT CHECK (before any processing)       │
│ Is input quit/bye/done/exit? → skip rest │
└──────────────┬─────────────────────────┘
               │ No → continue
               ▼
┌──────────────────────────────────────────┐
│ SMART TOP_K SELECTION                    │
│ "show all" → fetch 15                    │
│ "find bid GEM/" → fetch 2-3              │
│ Default → fetch 5                        │
└──────────────┬─────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ LEG 1: DENSE RETRIEVAL (BGE)             │
│ • BGE query prompt instruction prefix    │
│ • BAAI/bge-base-en-v1.5 embeddings       │
│ • Fetch top 40 candidates from ChromaDB  │
└──────────────┬─────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ LEG 2: SPARSE RETRIEVAL (BM25Okapi)      │
│ • Tokenize query                         │
│ • Search metadata-enriched corpus        │
│ • Fetch top 40 candidate chunks          │
└──────────────┬─────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ RECIPROCAL RANK FUSION (RRF) & DEDUP     │
│ • Combine dense + sparse rank lists      │
│ • Keep best scoring chunk per unique Bid │
└──────────────┬─────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ CROSS-ENCODER RERANKING                  │
│ • BAAI/bge-reranker-base CrossEncoder    │
│ • Compute Sigmoid(logit) per pair        │
└──────────────┬─────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ WEIGHTED FINAL SCORE & 70% CUTOFF FILTER │
│ Final = (rerank * 0.6)                   │
│       + (semantic * 0.25)                │
│       + (bm25 * 0.15)                    │
│ Cutoff: Drop scores < 70% of top match   │
└──────────────┬─────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ LLM Answer Generation (optional)         │
│ OR Retrieval-Only with Score Breakdown   │
└──────────────────────────────────────────┘
```

---

## Example 1: Simple Query — "Laptops"

### Database Setup

```
Query: "Laptops"
top_k: 5 (default)

Stored bids:
  Bid 1: Item="Dell Laptops 15-inch", Dept="IT Department", Type="Product"
  Bid 2: Item="Office Furniture Set", Dept="Admin Department", Type="Product"
  Bid 3: Item="Laptop Protective Carrying Bags", Dept="Stationery", Type="Product"
  Bid 4: Item="Computer Server Hardware", Dept="IT Department", Type="Product"
  Bid 5: Item="Enterprise Network Switches", Dept="IT Department", Type="Product"
```

### Step 1: BGE Query Embedding

```
Input:  "Represent this sentence for searching relevant passages: Laptops"
Model:  BAAI/bge-base-en-v1.5 (768-dimensional dense vector)
```

### Step 2: Dual Retrieval (Dense + Sparse) & RRF

Dense retrieval returns Bid 1 (dist=0.08), Bid 3 (dist=0.35), Bid 4 (dist=0.42), Bid 5 (dist=0.68), Bid 2 (dist=0.89).  
BM25 retrieval matches "laptops" in Bid 1 (score=18.5 → norm=0.925) and Bid 3 (score=8.0 → norm=0.40).

Reciprocal Rank Fusion aggregates the candidate list, deduplicating chunks so only the top chunk per Bid No enters Cross-Encoder reranking.

### Step 3: Cross-Encoder Reranking & Weighted Combination

#### **Bid 1 (Dell Laptops 15-inch)**

```
Dense Score (semantic) = 1.0 - 0.08 = 0.9200
BM25 Score (keyword)   = 0.9250
Cross-Encoder Reranker = Sigmoid(4.82) = 0.9920

Weighted Final Score:
  = (0.9920 × 0.60) + (0.9200 × 0.25) + (0.9250 × 0.15)
  = 0.5952 + 0.2300 + 0.1387
  = 0.9639  ✓ TOP MATCH
```

#### **Bid 3 (Laptop Protective Carrying Bags)**

```
Dense Score (semantic) = 1.0 - 0.35 = 0.6500
BM25 Score (keyword)   = 0.4000
Cross-Encoder Reranker = Sigmoid(1.20) = 0.7685

Weighted Final Score:
  = (0.7685 × 0.60) + (0.6500 × 0.25) + (0.4000 × 0.15)
  = 0.4611 + 0.1625 + 0.0600
  = 0.6836  ✓ Retained (Score >= 0.9639 * 0.70 = 0.6747)
```

#### **Bid 4 (Computer Server Hardware)**

```
Dense Score (semantic) = 1.0 - 0.42 = 0.5800
BM25 Score (keyword)   = 0.0000
Cross-Encoder Reranker = Sigmoid(-1.50) = 0.1824

Weighted Final Score:
  = (0.1824 × 0.60) + (0.5800 × 0.25) + (0.0000 × 0.15)
  = 0.1094 + 0.1450 + 0.0000
  = 0.2544  ⬇ Filtered out by 70% relative threshold (0.2544 < 0.6747)
```

#### **Bid 2 (Office Furniture Set)**

```
Dense Score (semantic) = 0.1100
BM25 Score (keyword)   = 0.0000
Cross-Encoder Reranker = Sigmoid(-4.50) = 0.0109

Weighted Final Score = 0.0340  ⬇ Filtered out
```

### Step 4: Final Output Generation

The system filters out low-confidence matches using the 70% relative threshold rule and returns Bid 1 as the top result with full score breakdown:

```
1. Bid No    : GEM/2026/B/7549944
   Item      : Dell Laptops 15-inch Intel i7
   Dept      : IT Department
   Type      : Product Bid/RAs
   End Date  : 30-05-2026 16:00:00
   URL       : https://bidplus.gem.gov.in/...
   ──────────────────────────────────────
   Score     : 96.39%  (rerank 99.20% | dense 92.00% | bm25 92.50%)
```

- ✗ No keyword match (query "laptops" ≠ field word "laptop")
- Purely semantic result

**Why Bid 4 is third**:
- ✓ Moderate semantic match (0.58, hardware is related)
- ✗ No keyword match
- ✓ Right department (IT)

---

## Example 2: Multi-Word Query — "IT Department Hardware Procurement"

### Setup

```
Query: "IT Department Hardware Procurement"
top_k: 5
```

### Query Processing

```
Raw query: "IT Department Hardware Procurement"
↓
Stop word removal: Remove "of", "the", "for", "in", "is"
↓
Query words: {"it", "department", "hardware", "procurement"}
↓
Query vector: [0.451, -0.234, 0.567, ..., -0.123]
```

### Semantic Scores

```
Bid A: "Dell Servers IT Equipment"
  Distance: 0.18
  Semantic: 1 - 0.18 = 0.82

Bid B: "Office Furniture General"
  Distance: 0.91
  Semantic: 1 - 0.91 = 0.09

Bid C: "IT Infrastructure Procurement Services"
  Distance: 0.08
  Semantic: 1 - 0.08 = 0.92
```

### Keyword Scores

```
Bid A: full_item_name="Dell Servers IT Equipment", department="IT"
  
  full_item_name words: {"dell", "servers", "it", "equipment"}
  Query matches: {"it"} = 1 out of 4 query words
  Contribution: 3.0 × (1/4) = 0.75
  
  department words: {"it"}
  Query matches: {"it"} = 1 out of 4 query words
  Contribution: 1.5 × (1/4) = 0.375
  
  keyword_score = min(1.0, (0.75 + 0.375) / 6.5) = 0.173

Bid C: full_item_name="IT Infrastructure Procurement Services", department="Finance"
  
  full_item_name words: {"it", "infrastructure", "procurement", "services"}
  Query matches: {"it", "procurement"} = 2 out of 4 query words
  Contribution: 3.0 × (2/4) = 1.5
  
  department words: {"finance"}
  Query matches: {} = 0
  Contribution: 0
  
  keyword_score = min(1.0, 1.5 / 6.5) = 0.231
```

### Hybrid Calculation

```
Bid A:
  hybrid = (0.82 × 0.6) + (0.173 × 0.4)
         = 0.492 + 0.069
         = 0.561

Bid C:
  hybrid = (0.92 × 0.6) + (0.231 × 0.4)
         = 0.552 + 0.092
         = 0.644

Result: Bid C ranks higher!
```

### Key Insight

**Bid C wins because**:
- Better semantic match (0.92 vs 0.82) — "IT Infrastructure Procurement" is semantically closer
- Better keyword match (2 words match vs 1 word match)
- Hybrid balances both factors

This shows how hybrid scoring prevents missing results that are semantically perfect but lack exact keywords.

---

## Example 3: How Different Weights Change Results

### Query: "Service Bid"

```
Bid X: "Service Bid/RAs - Consulting"
  Semantic score: 0.95 (exact match in embeddings)
  Keyword score: 0.90 (both words present)

Bid Y: "Product Hardware Supply"
  Semantic score: 0.45 (semantically related but different)
  Keyword score: 0.10 (no keyword match)
```

### Scoring with Different Weights

**Default (60% semantic, 40% keyword)**:
```
Bid X: (0.95 × 0.6) + (0.90 × 0.4) = 0.57 + 0.36 = 0.93 ✓ Wins
Bid Y: (0.45 × 0.6) + (0.10 × 0.4) = 0.27 + 0.04 = 0.31
```

**More semantic (80% semantic, 20% keyword)**:
```
Bid X: (0.95 × 0.8) + (0.90 × 0.2) = 0.76 + 0.18 = 0.94 ✓ Still wins
Bid Y: (0.45 × 0.8) + (0.10 × 0.2) = 0.36 + 0.02 = 0.38
```

**More keyword (40% semantic, 60% keyword)**:
```
Bid X: (0.95 × 0.4) + (0.90 × 0.6) = 0.38 + 0.54 = 0.92 ✓ Still wins
Bid Y: (0.45 × 0.4) + (0.10 × 0.6) = 0.18 + 0.06 = 0.24
```

### When Weights Matter Most

```
Query: "computer" (ambiguous — could mean many things)

Bid A: "Laptop Computer" (perfect keyword match)
  Semantic: 0.70
  Keyword: 0.95

Bid B: "IT Hardware Infrastructure" (semantically related)
  Semantic: 0.85
  Keyword: 0.10

With 60/40 weights (default):
  Bid A: (0.70 × 0.6) + (0.95 × 0.4) = 0.42 + 0.38 = 0.80
  Bid B: (0.85 × 0.6) + (0.10 × 0.4) = 0.51 + 0.04 = 0.55
  → Bid A wins (correct! exact match)

With 80/20 weights (semantic heavy):
  Bid A: (0.70 × 0.8) + (0.95 × 0.2) = 0.56 + 0.19 = 0.75
  Bid B: (0.85 × 0.8) + (0.10 × 0.2) = 0.68 + 0.02 = 0.70
  → Bid A still wins (by smaller margin — Bid B creeps up)

With 40/60 weights (keyword heavy):
  Bid A: (0.70 × 0.4) + (0.95 × 0.6) = 0.28 + 0.57 = 0.85
  Bid B: (0.85 × 0.4) + (0.10 × 0.6) = 0.34 + 0.06 = 0.40
  → Bid A wins even stronger (keyword dominates)
```

---

## Field Weight Impact

### Query: "IT Department Laptops"

```
Bid: "Dell Laptops", department="IT"
Query words: {"it", "department", "laptops"}
```

### With Default Weights

```
fields_text = {
    "full_item_name": 3.0,
    "department": 1.5,
    "bid_type": 1.0,
    "product_type": 1.0,
}

full_item_name: "Dell Laptops"
  Words: {"dell", "laptops"}
  Matches: {"laptops"} = 1 out of 3 query words
  Score: 3.0 × (1/3) = 1.0

department: "IT"
  Words: {"it"}
  Matches: {"it"} = 1 out of 3 query words
  Score: 1.5 × (1/3) = 0.5

Total: min(1.0, 1.5 / 6.5) = 0.23
```

### With Adjusted Weights (Prioritize Department)

```
fields_text = {
    "full_item_name": 3.0,
    "department": 3.0,    # ← Doubled from 1.5
    "bid_type": 1.0,
    "product_type": 1.0,
}

department: "IT"
  Score: 3.0 × (1/3) = 1.0  (was 0.5)

Total: min(1.0, 2.0 / 8.0) = 0.25  (was 0.23)
↑ Department matches now contribute more to ranking
```

---

## Score Distribution Patterns

### Pattern 1: Good Results (Typical)

```
Top 5 scores:
1. 0.85  ✓ Perfect match (semantic + keyword)
2. 0.72  ✓ Good match (high semantic)
3. 0.58  ✓ Okay match (moderate semantic + keyword)
4. 0.45  ⚠ Weak match (one factor high, other low)
5. 0.32  ⚠ Very weak (both factors moderate)

Pattern: Scores 0.7-0.9 for relevant results
         Scores 0.3-0.5 for borderline results
         Scores < 0.3 for irrelevant results
```

### Pattern 2: Semantic Heavy (weights 0.8/0.2)

```
Top 5 scores:
1. 0.82
2. 0.78
3. 0.65
4. 0.58
5. 0.51

Pattern: Narrower spread, only semantic similarity matters
         May miss keyword-exact matches
```

### Pattern 3: Keyword Heavy (weights 0.3/0.7)

```
Top 5 scores:
1. 0.91  (high keyword match)
2. 0.65  (medium keyword match)
3. 0.58  (keyword + some semantic)
4. 0.42
5. 0.38

Pattern: Drops suddenly after keyword-matched results
         Synonym/related results ranked lower
```

---

## Score Breakdown in Retrieval-Only Mode

When `RAG_LLM_PROVIDER=""`, each result shows the full breakdown:

```
1. Bid No    : GEM/2026/B/7382409
   Item      : Dell Laptops 15 inch
   Dept      : Ministry of Electronics
   Type      : Product Bid/RAs
   End Date  : 11-01-2026 16:00:00
   Est. Value: 5000000 INR
   URL       : https://bidplus.gem.gov.in/...
   ──────────────────────────────────────
   Overall Score : 71.20%
     • Semantic (60%)  : 88.00%
     • Keyword  (40%)  : 46.00%
```

This breakdown helps you understand:
- **High semantic, low keyword**: Semantically related but no exact word match
- **Low semantic, high keyword**: Exact words present but different meaning
- **Both high**: Strong match on all fronts

---

## Common Scoring Scenarios

### Scenario: Generic Query

```
Query: "Bids"

All bids will have similar low scores because:
- "bids" is too generic for semantic differentiation
- "bids" appears in bid_type fields but with low weight

Result: Very close scores, ordering mostly random
Fix: Use a more specific query
```

### Scenario: Specific Query

```
Query: "Dell Laptop Enterprise"

Bid A: "Dell Laptops 15 inch"
  Semantic: 0.72 (exact match)
  Keyword: 0.80 (matches "Dell", "Laptop")
  Hybrid: 0.75

Bid B: "General Hardware"
  Semantic: 0.35 (some related concepts)
  Keyword: 0.05 (no matches)
  Hybrid: 0.23

Result: Clear winner (0.75 vs 0.23)
Why: Specific query has strong keyword signals + semantic match
```

### Scenario: Stop Words Only

```
Query: "for the"

Query words after stop word removal: {} (empty!)
→ _keyword_score returns 0.5 (neutral)
→ Only semantic score differentiates results

Fix: Use meaningful query words
```

---

## Debugging Scores

When results don't seem right:

### Check 1: Score Breakdown in Chat

```bash
python main.py --chat
You > /search "your query"

# Output shows:
# • [GEM/2026/B/123]  Dell Laptops  | End: 11-01-2026  | 71.20%
# (full_item_name shown, not raw chunk text)
```

### Check 2: Retrieval-Only Mode

```bash
# Set in .env:
RAG_LLM_PROVIDER=

# Then run:
python main.py --ask "your query"

# Output shows full breakdown:
# Overall Score : 71%
#   • Semantic (60%)  : 88%
#   • Keyword  (40%)  : 46%
```

### Check 3: Vector Store Health

```bash
python main.py --stats

# Good indicators:
# - Vector store chunks: > SQLite bids
# - Ratio: 3-5:1
# - No error messages
```

---

## Formula Reference Sheet

```
┌─────────────────────────────────────────────────────┐
│ SEMANTIC SCORING                                    │
├─────────────────────────────────────────────────────┤
│ semantic_score = 1 - cosine_distance(query, chunk) │
│ Range: 0 (opposite) to 1 (identical)               │
└─────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────┐
│ KEYWORD SCORING  (_keyword_score)                      │
├────────────────────────────────────────────────────────┤
│ 1. Remove stop words from query                        │
│    stop_words = {for, the, a, an, and, or, in, of, is} │
│ 2. If all words removed → return 0.5 (neutral)         │
│ 3. For each field:                                     │
│    matches = count(query_words ∩ field_words)          │
│    contribution = field_weight × (matches / n_queries) │
│ 4. keyword_score = min(1.0, Σcontribution / Σweights)  │
│ Range: 0 (no matches) to 1 (all matches in all fields) │
└────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│ HYBRID SCORING                                       │
├──────────────────────────────────────────────────────┤
│ hybrid = (semantic × 0.6) + (keyword × 0.4)         │
│ Range: 0 (completely irrelevant) to 1 (perfect)     │
│                                                      │
│ Adjust weights:                                      │
│ hybrid = (semantic × w_s) + (keyword × w_k)         │
│ where: w_s + w_k = 1.0                              │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│ FIELD WEIGHT SCORING                                 │
├──────────────────────────────────────────────────────┤
│ Default weights:                                     │
│  full_item_name: 3.0  (highest — item name match)   │
│  department: 1.5                                     │
│  bid_type: 1.0                                       │
│  product_type: 1.0                                   │
│  max_possible: 6.5                                   │
└──────────────────────────────────────────────────────┘
```

---

## Interactive Scoring Calculator

To manually calculate scores:

```python
# Hybrid formula:
def calculate_hybrid_score(semantic, keyword, w_s=0.6, w_k=0.4):
    return (semantic * w_s) + (keyword * w_k)

# Examples:
calculate_hybrid_score(0.88, 0.46)  # Returns 0.712 (Bid 1 from Example 1)
calculate_hybrid_score(0.65, 0.00)  # Returns 0.390 (Bid 3 from Example 1)

# Try different weights:
calculate_hybrid_score(0.88, 0.46, w_s=0.7, w_k=0.3)  # 0.754
calculate_hybrid_score(0.88, 0.46, w_s=0.5, w_k=0.5)  # 0.670
```

---

## Summary

The RAG scoring system is:

1. **Transparent**: You can see both components (semantic + keyword) in retrieval-only mode
2. **Tunable**: Adjust weights to match your intent
3. **Debuggable**: Scores tell you what's matching and why
4. **Balanced**: Combines different matching strategies
5. **Stop-word aware**: Common words don't pollute keyword matching

**Key principle**: No single signal (semantic or keyword) is perfect. Hybrid gives best of both worlds.
