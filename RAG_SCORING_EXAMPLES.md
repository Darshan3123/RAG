# RAG Scoring Deep Dive — Visual Guide

> **How exactly are scores calculated?** Step-by-step examples with real numbers  
> **Last Updated:** July 2026  
> **For:** Understanding the hybrid scoring formula through concrete examples

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
│ Embed Query                              │
│ "IT laptops" → 384-dim vector            │
│ [0.234, -0.456, 0.892, ..., 0.045]      │
└──────────────┬─────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ Fetch ~top_k*4 chunks from ChromaDB      │
│ (over-fetch for deduplication)           │
└──────────────┬─────────────────────────┘
               │
         ┌─────┴──────────────┐
         ▼                    ▼
    FOR EACH CHUNK (calculate dual scores):
    
    TRACK 1: SEMANTIC SCORING
    ├─ cosine_dist = distance(query_vec, chunk_vec)
    ├─ semantic_score = 1 - cosine_dist
    └─ Range: 0 (unrelated) to 1 (perfect match)
    
    TRACK 2: KEYWORD SCORING (_keyword_score)
    ├─ Split query: "IT" + "laptops"
    ├─ Remove stop words (for, the, a, an, and, or, in, of, is)
    ├─ Remaining: "IT" + "laptops"
    ├─ Match in fields:
    │   • full_item_name     weight=3.0  ← highest weight
    │   • department         weight=1.5
    │   • bid_type           weight=1.0
    │   • product_type       weight=1.0
    ├─ Count matches
    └─ keyword_score = normalized (0 to 1)
    
    TRACK 3: HYBRID COMBINATION
    └─ final = (semantic × 0.6) + (keyword × 0.4)

┌──────────────────────────────────────────┐
│ Aggregate by Bid ID                      │
│ • Multiple chunks per bid (from overlap) │
│ • Keep highest scoring chunk per bid     │
│ • Deduplicated results                   │
└──────────────┬─────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ Sort by Hybrid Score (highest first)     │
│ Return top_k unique bids                 │
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
  Bid 1: Item="Dell Laptops", Dept="IT", Type="Product"
  Bid 2: Item="Office Furniture", Dept="Admin", Type="Product"
  Bid 3: Item="Laptop Bags", Dept="Stationery", Type="Product"
  Bid 4: Item="Computer Hardware", Dept="IT", Type="Product"
  Bid 5: Item="Network Switches", Dept="IT", Type="Product"
```

### Step 1: Query Embedding

```
Input:  "Laptops"
Model:  all-MiniLM-L6-v2 (384-dimensional)
Output: query_vec = [0.234, -0.456, 0.892, ..., 0.045]
```

### Step 2: Fetch Candidates

ChromaDB returns all 5 bids (plus multiple chunks of each):

```
Raw fetch (20 chunks):
├─ Bid 1 chunk 0: text="Dell Laptops 15-inch Intel...", distance=0.12
├─ Bid 1 chunk 1: text="Dell Laptops specs warranty...", distance=0.15
├─ Bid 2 chunk 0: text="Office Furniture", distance=0.89
├─ Bid 3 chunk 0: text="Laptop Bags leather", distance=0.35
├─ Bid 4 chunk 0: text="Computer Hardware servers", distance=0.42
├─ Bid 4 chunk 1: text="Hardware specs networking", distance=0.51
├─ Bid 5 chunk 0: text="Network Switches enterprise", distance=0.68
└─ (more chunks...)
```

### Step 3: Calculate Scores for Each Chunk

#### **Chunk: Bid 1 (Dell Laptops)**

```
Distance from query: 0.12
Semantic score = 1 - 0.12 = 0.88

Keyword Analysis (_keyword_score):
Query words after stop word removal: {"laptops"}

Field matching:
┌─ full_item_name: "Dell Laptops"
│  Words: {"dell", "laptops"}
│  Matches: {"laptops"} = 1 match out of 1 query word
│  Contribution: 3.0 × (1/1) = 3.0
│
├─ department: "IT"
│  Words: {"it"}
│  Matches: {} = 0 matches
│  Contribution: 0
│
├─ bid_type: "Product Bid/RAs"
│  Matches: {} = 0
│  Contribution: 0
│
└─ product_type: "Product"
   Matches: {} = 0
   Contribution: 0

Total keyword score = min(1.0, 3.0 / 6.5) = 0.46
(max_possible = 3.0 + 1.5 + 1.0 + 1.0 = 6.5)

✓ Hybrid Score = (0.88 × 0.6) + (0.46 × 0.4)
              = 0.528 + 0.184
              = 0.712
```

#### **Chunk: Bid 2 (Office Furniture)**

```
Distance from query: 0.89
Semantic score = 1 - 0.89 = 0.11

Keyword Analysis:
Query words: {"laptops"}

Field matching:
┌─ full_item_name: "Office Furniture"
│  Words: {"office", "furniture"}
│  Matches: {} = 0 matches
│  Contribution: 0

Total keyword score = 0 / 6.5 = 0.00

✗ Hybrid Score = (0.11 × 0.6) + (0.00 × 0.4)
              = 0.066 + 0.000
              = 0.066  ← Very low!
```

#### **Chunk: Bid 3 (Laptop Bags)**

```
Distance from query: 0.35
Semantic score = 1 - 0.35 = 0.65

Keyword Analysis:
Query words: {"laptops"}

Field matching:
┌─ full_item_name: "Laptop Bags"
│  Words: {"laptop", "bags"}
│  Matches: {} = 0 (query has "laptops", field has "laptop" — no exact match)
│  Contribution: 0

Total keyword score = 0 / 6.5 = 0.00

✓ Hybrid Score = (0.65 × 0.6) + (0.00 × 0.4)
              = 0.390 + 0.000
              = 0.390  ← Semantic only
```

#### **Chunk: Bid 4 (Computer Hardware)**

```
Distance from query: 0.42
Semantic score = 1 - 0.42 = 0.58

Keyword Analysis:
Query words: {"laptops"}

Field matching:
┌─ full_item_name: "Computer Hardware"
│  Words: {"computer", "hardware"}
│  Matches: {} = 0 matches
│  Contribution: 0

Total keyword score = 0 / 6.5 = 0.00

✗ Hybrid Score = (0.58 × 0.6) + (0.00 × 0.4)
              = 0.348 + 0.000
              = 0.348
```

#### **Chunk: Bid 5 (Network Switches)**

```
Distance from query: 0.68
Semantic score = 1 - 0.68 = 0.32

No keyword matches.

✗ Hybrid Score = (0.32 × 0.6) + (0.00 × 0.4) = 0.192
```

### Step 4: Aggregate by Bid ID

For each bid, keep the highest scoring chunk:

```
Bid 1: Max chunk score = 0.712 ✓ Winner!
Bid 3: Max chunk score = 0.390
Bid 4: Max chunk score = 0.348
Bid 5: Max chunk score = 0.192
Bid 2: Max chunk score = 0.066
```

### Step 5: Sort and Return Top-K

```
Results (top_k=5, sorted by hybrid score):

1. Bid 1 (Dell Laptops)
   ├─ Score: 0.712 (71.2%)
   ├─ Semantic: 0.88 (88%)
   ├─ Keyword: 0.46 (46%)
   └─ Type: Product | Dept: IT | Value: 50 Lakhs

2. Bid 3 (Laptop Bags)
   ├─ Score: 0.390 (39.0%)
   ├─ Semantic: 0.65 (65%)
   ├─ Keyword: 0.00 (0%)
   └─ Type: Product | Dept: Stationery | Value: 2 Lakhs

3. Bid 4 (Computer Hardware)
   ├─ Score: 0.348 (34.8%)
   ├─ Semantic: 0.58 (58%)
   ├─ Keyword: 0.00 (0%)
   └─ Type: Product | Dept: IT | Value: 75 Lakhs

4. Bid 5 (Network Switches)
   ├─ Score: 0.192 (19.2%)
   ├─ Semantic: 0.32 (32%)
   ├─ Keyword: 0.00 (0%)
   └─ Type: Product | Dept: IT | Value: 30 Lakhs

5. Bid 2 (Office Furniture)
   ├─ Score: 0.066 (6.6%)
   ├─ Semantic: 0.11 (11%)
   ├─ Keyword: 0.00 (0%)
   └─ Type: Product | Dept: Admin | Value: 10 Lakhs
```

### Analysis

**Why Bid 1 wins**:
- ✓ Exact keyword match ("laptops" in item name)
- ✓ High semantic similarity (0.88)
- ✓ Keyword score boosted by high field weight (3.0 for item name)

**Why Bid 3 is second**:
- ✓ Moderate semantic match (0.65, "laptop bags" is related)
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
