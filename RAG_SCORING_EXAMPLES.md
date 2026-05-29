# RAG Scoring Deep Dive — Visual Guide

> How exactly are scores calculated? Step-by-step examples  
> **Last Updated**: May 29, 2026

---

## The Scoring Flow

```
┌──────────────────────────────┐
│ User Query                   │
│ "Show me IT laptops"         │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Embed Query                  │
│ query_vec = [0.23, -0.45, ...]
│ (384 dimensions)             │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Fetch ~20 chunks from DB     │
│ (for top_k=5, fetch_n=20)    │
└──────────────┬───────────────┘
               │
         ┌─────┴─────┐
         ▼           ▼
    FOR EACH CHUNK:
    
    ├─ Calculate Semantic Score
    │  ├─ distance = cosine_distance(query, chunk_vec)
    │  └─ semantic_score = 1 - distance
    │
    ├─ Calculate Keyword Score
    │  ├─ Find query keywords in bid fields
    │  ├─ Apply field weights
    │  └─ keyword_score = total_matches / max_possible
    │
    └─ Calculate Hybrid Score
       ├─ hybrid = (semantic * 0.6) + (keyword * 0.4)
       └─ hybrid_score = 0.0 to 1.0

┌──────────────────────────────────────┐
│ Aggregate by Bid ID                  │
│ Keep highest score per bid_no        │
│ (deduplication)                      │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ Sort by Hybrid Score (descending)    │
│ Return top_k results                 │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [Optional] Send to LLM for answer    │
│ or return retrieval-only results     │
└──────────────────────────────────────┘
```

---

## Example 1: Simple Query — "Laptops"

### Setup

```
Query: "Laptops"
top_k: 5
RAG_TOP_K=5

Stored in database:
Bid 1: Item="Dell Laptops", Dept="IT", Type="Product", Value="50 Lakhs"
Bid 2: Item="Office Furniture", Dept="Admin", Type="Product", Value="10 Lakhs"
Bid 3: Item="Laptop Bags", Dept="Stationery", Type="Product", Value="2 Lakhs"
Bid 4: Item="Computer Hardware", Dept="IT", Type="Product", Value="75 Lakhs"
Bid 5: Item="Network Switches", Dept="IT", Type="Product", Value="30 Lakhs"
```

### Step 1: Query Embedding

```
Query text: "Laptops"
↓
Encode using SentenceTransformer
↓
Query vector: [0.324, -0.156, 0.892, ..., 0.045]  (384 dims)
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

Keyword Analysis:
Query words: {"laptop", "laptops"}  (after stop word removal)

Field matching:
┌─ full_item_name: "Dell Laptops"
│  Words: {"dell", "laptops"}
│  Matches: {"laptops"} = 1 match
│  Contribution: 3.0 × (1/2) = 1.5
│
├─ department: "IT"
│  Words: {"it"}
│  Matches: {} = 0 matches
│  Contribution: 0
│
├─ bid_type: "Product"
│  Words: {"product"}
│  Matches: {} = 0 matches
│  Contribution: 0
│
└─ product_type: "Product"
   Words: {"product"}
   Matches: {} = 0 matches
   Contribution: 0

Total keyword score = 1.5 / 6.5 = 0.23
(max_possible = 3.0 + 1.5 + 1.0 + 1.0 = 6.5)

✓ Hybrid Score = (0.88 × 0.6) + (0.23 × 0.4)
              = 0.528 + 0.092
              = 0.620
```

#### **Chunk: Bid 2 (Office Furniture)**

```
Distance from query: 0.89
Semantic score = 1 - 0.89 = 0.11

Keyword Analysis:
Query words: {"laptop", "laptops"}

Field matching:
┌─ full_item_name: "Office Furniture"
│  Words: {"office", "furniture"}
│  Matches: {} = 0 matches
│  Contribution: 0
│
├─ department: "Admin"
├─ bid_type: "Product"
└─ product_type: "Product"
   All: 0 matches

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
Query words: {"laptop", "laptops"}

Field matching:
┌─ full_item_name: "Laptop Bags"
│  Words: {"laptop", "bags"}
│  Matches: {"laptop"} = 1 match
│  Contribution: 3.0 × (1/2) = 1.5
│
└─ department: "Stationery"
   (no match)

Total keyword score = 1.5 / 6.5 = 0.23

✓ Hybrid Score = (0.65 × 0.6) + (0.23 × 0.4)
              = 0.390 + 0.092
              = 0.482  ← Still less than Bid 1
```

#### **Chunk: Bid 4 (Computer Hardware)**

```
Distance from query: 0.42
Semantic score = 1 - 0.42 = 0.58

Keyword Analysis:
Query words: {"laptop", "laptops"}

Field matching:
┌─ full_item_name: "Computer Hardware"
│  Words: {"computer", "hardware"}
│  Matches: {} = 0 matches (not "laptop")
│  Contribution: 0
│
└─ (no other matches)

Total keyword score = 0 / 6.5 = 0.00

✗ Hybrid Score = (0.58 × 0.6) + (0.00 × 0.4)
              = 0.348 + 0.000
              = 0.348
```

#### **Chunk: Bid 5 (Network Switches)**

```
Distance from query: 0.68
Semantic score = 1 - 0.68 = 0.32

Keyword Analysis:
Query words: {"laptop", "laptops"}

No matches in any field.

Total keyword score = 0 / 6.5 = 0.00

✗ Hybrid Score = (0.32 × 0.6) + (0.00 × 0.4)
              = 0.192 + 0.000
              = 0.192
```

### Step 4: Aggregate by Bid ID

For each bid, keep the highest scoring chunk:

```
Bid 1: Max chunk score = 0.620 ✓ Winner!
Bid 2: Max chunk score = 0.066
Bid 3: Max chunk score = 0.482
Bid 4: Max chunk score = 0.348
Bid 5: Max chunk score = 0.192
```

### Step 5: Sort and Return Top-K

```
Results (top_k=5, sorted by hybrid score):

1. Bid 1 (Dell Laptops)
   ├─ Score: 0.620 (62.0%)
   ├─ Semantic: 0.88 (88%)
   ├─ Keyword: 0.23 (23%)
   └─ Type: Product | Dept: IT | Value: 50 Lakhs

2. Bid 3 (Laptop Bags)
   ├─ Score: 0.482 (48.2%)
   ├─ Semantic: 0.65 (65%)
   ├─ Keyword: 0.23 (23%)
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
- ✓ Exact keyword match ("Laptops")
- ✓ High semantic similarity (0.88)
- ✓ Relevant department (IT)

**Why Bid 3 is second**:
- ✓ Keyword match ("Laptop")
- ✓ Moderate semantic match (0.65)
- ✗ Wrong department (Stationery, not IT)

**Why Bid 4 is third**:
- ✓ High semantic match (0.58, related to laptops)
- ✗ No keyword match (not called "laptop")
- ✓ Right department (IT)

---

## Example 2: Complex Query — "IT Department Hardware Procurement"

### Setup

```
Query: "IT Department Hardware Procurement"
top_k: 5
```

### Query Processing

```
Raw query: "IT Department Hardware Procurement"
↓
Stop word removal: Remove "of", "the", "for"
↓
Query words: {"IT", "Department", "Hardware", "Procurement"}
↓
Query vector: [0.451, -0.234, 0.567, ..., -0.123]
```

### Semantic Scores

Let's say ChromaDB returns:

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
Bid A: "Dell Servers IT Equipment"
  full_item_name: "Dell Servers IT Equipment"
  Words: {"dell", "servers", "it", "equipment"}
  Query matches: {"IT"} = 1/4 words match
  Contribution: 3.0 × (1/4) = 0.75
  
  department: "IT"
  Words: {"it"}
  Query matches: {"IT"} = 1/1 words match
  Contribution: 1.5 × (1/1) = 1.5
  
  keyword_score = (0.75 + 1.5) / 6.5 = 0.35

Bid C: "IT Infrastructure Procurement Services"
  full_item_name: "IT Infrastructure Procurement Services"
  Words: {"it", "infrastructure", "procurement", "services"}
  Query matches: {"IT", "Procurement"} = 2/4 words match
  Contribution: 3.0 × (2/4) = 1.5
  
  department: "Finance"
  Words: {"finance"}
  Query matches: {} = 0
  Contribution: 0
  
  keyword_score = 1.5 / 6.5 = 0.23
```

### Hybrid Calculation

```
Bid A:
  hybrid = (0.82 × 0.6) + (0.35 × 0.4)
         = 0.492 + 0.140
         = 0.632

Bid C:
  hybrid = (0.92 × 0.6) + (0.23 × 0.4)
         = 0.552 + 0.092
         = 0.644

Result: Bid C ranks higher!
```

### Key Insight

**Bid C wins because**:
- Slightly better semantic match (0.92 vs 0.82)
- Both have good keyword matching
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
Difference: +0.07 for X, +0.07 for Y (same impact)
```

**More keyword (40% semantic, 60% keyword)**:
```
Bid X: (0.95 × 0.4) + (0.90 × 0.6) = 0.38 + 0.54 = 0.92 ✓ Still wins
Bid Y: (0.45 × 0.4) + (0.10 × 0.6) = 0.18 + 0.06 = 0.24
Difference: -0.01 for X, -0.07 for Y (Y loses more)
```

### When Weights Matter

```
Query: "computer" (could mean many things)

Bid A: "Laptop Computer" (perfect keyword match)
  Semantic: 0.70
  Keyword: 0.95

Bid B: "IT Hardware Infrastructure" (semantically related)
  Semantic: 0.85
  Keyword: 0.10

With 60/40 weights:
  Bid A: (0.70 × 0.6) + (0.95 × 0.4) = 0.42 + 0.38 = 0.80
  Bid B: (0.85 × 0.6) + (0.10 × 0.4) = 0.51 + 0.04 = 0.55
  → Bid A wins (correct! exact match)

With 80/20 weights:
  Bid A: (0.70 × 0.8) + (0.95 × 0.2) = 0.56 + 0.19 = 0.75
  Bid B: (0.85 × 0.8) + (0.10 × 0.2) = 0.68 + 0.02 = 0.70
  → Bid A still wins (by less margin)

With 40/60 weights:
  Bid A: (0.70 × 0.4) + (0.95 × 0.6) = 0.28 + 0.57 = 0.85
  Bid B: (0.85 × 0.4) + (0.10 × 0.6) = 0.34 + 0.06 = 0.40
  → Bid A wins even stronger (keyword matters most)
```

---

## Field Weight Impact

### Query: "IT Department Laptops"

```
Bid: "Dell Laptops"
  full_item_name: "Dell Laptops"
  department: "IT"
  bid_type: "Product"
  product_type: "Product"

Query words: {"IT", "Department", "Laptops"}
```

### With Default Weights

```
fields_text = {
    "full_item_name": 3.0,
    "department": 1.5,
    "bid_type": 1.0,
    "product_type": 1.0,
}

full_item_name matches:
  Words: {"dell", "laptops"}
  Matches: {"laptops"} = 1/3
  Score: 3.0 × (1/3) = 1.0

department matches:
  Words: {"it"}
  Matches: {"it"} = 1/3
  Score: 1.5 × (1/3) = 0.5

bid_type, product_type: No matches

Total: 1.5 / 6.5 = 0.23
```

### With Adjusted Weights (Prioritize Department)

```
fields_text = {
    "full_item_name": 3.0,
    "department": 3.0,    # ← Doubled from 1.5
    "bid_type": 1.0,
    "product_type": 1.0,
}

department matches:
  Score: 3.0 × (1/3) = 1.0  (was 0.5)

Total: 2.0 / 7.5 = 0.27  (was 0.23)
↑ Department matches now contribute more
```

### Result

With higher department weight, bids from IT department score higher, even if item names don't match perfectly.

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

### Pattern 2: Skewed Semantic (Semantic Heavy)

```
If weights are (0.8, 0.2):

Top 5 scores:
1. 0.82
2. 0.78
3. 0.65
4. 0.58
5. 0.51

Pattern: Narrower spread
         Only semantic similarity matters
         May miss keyword-exact matches
```

### Pattern 3: Skewed Keyword (Keyword Heavy)

```
If weights are (0.3, 0.7):

Top 5 scores:
1. 0.91  (high keyword match)
2. 0.65  (medium keyword match)
3. 0.58  (keyword + some semantic)
4. 0.42
5. 0.38

Pattern: Drops suddenly after keyword-matched results
         Synonym/related results ranked lower
         More precise but misses intent-based matches
```

---

## Common Scoring Scenarios

### Scenario: Generic Query

```
Query: "Bids"

Bid A: "Product Bid/RAs - Software"
  Semantic: 0.45 (just the word "bid")
  Keyword: 0.15 (word "bid" in field, but low weight)
  Hybrid: 0.35

Bid B: "Government Service Bids"
  Semantic: 0.48
  Keyword: 0.15
  Hybrid: 0.37

Result: Very close scores (0.35 vs 0.37)
Why: Query too generic, semantic only source of differentiation
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

---

## Debugging Scores

When results don't seem right:

### Check 1: Semantic Score Breakdown

```bash
# In chat mode:
python main.py --chat
You > /search "your query"

# Look for output like:
# Overall Score : 45%
#   • Semantic (60%)  : 65%
#   • Keyword  (40%)  : 15%

# If Semantic very low (< 30%): Wrong embedding model or query
# If Keyword very low (< 20%): Words not in bid fields
```

### Check 2: Field Extraction

```python
# File: rag/vector_store.py, line ~105

# Add debug logging:
log.debug(f"Query words: {query_words}")
log.debug(f"Field matches: {total_score}/{max_possible}")

# Rerun and check logs
```

### Check 3: Vector Store Health

```bash
python main.py --stats

# Good indicators:
# - Vector store chunks: > SQLite bids
# - Ratio: 3-5:1
# - No error messages

# Bad indicators:
# - chunks < bids (data loss?)
# - chunks > 100x bids (index corruption?)
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
│ KEYWORD SCORING                                        │
├────────────────────────────────────────────────────────┤
│ For each field:                                        │
│   matches = count(query_words ∩ field_words)         │
│   contribution = field_weight × (matches / n_queries) │
│                                                        │
│ keyword_score = min(1.0, Σcontribution / Σweights)    │
│ Range: 0 (no matches) to 1 (all matches in all fields)│
└────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│ HYBRID SCORING                                       │
├──────────────────────────────────────────────────────┤
│ hybrid = (semantic × 0.6) + (keyword × 0.4)         │
│ Range: 0 (completely irrelevant) to 1 (perfect)     │
│                                                      │
│ Can adjust weights:                                  │
│ hybrid = (semantic × w_s) + (keyword × w_k)         │
│ where: w_s + w_k = 1.0                              │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│ FIELD WEIGHT SCORING                                 │
├──────────────────────────────────────────────────────┤
│ score_component = field_weight × (matches / n_query) │
│                                                      │
│ Default weights:                                     │
│  full_item_name: 3.0                                 │
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
# Formula:
def calculate_hybrid_score(semantic, keyword, w_semantic=0.6, w_keyword=0.4):
    return (semantic * w_semantic) + (keyword * w_keyword)

# Example:
calculate_hybrid_score(0.87, 0.23)  # Returns 0.614

# Try different weights:
calculate_hybrid_score(0.87, 0.23, w_semantic=0.7, w_keyword=0.3)  # 0.638
calculate_hybrid_score(0.87, 0.23, w_semantic=0.5, w_keyword=0.5)  # 0.590
```

---

## Summary

The RAG scoring system is:

1. **Transparent**: You can see both components (semantic + keyword)
2. **Tunable**: Adjust weights to match your intent
3. **Debuggable**: Scores tell you what's matching and why
4. **Balanced**: Combines different matching strategies

**Key principle**: No single signal (semantic or keyword) is perfect. Hybrid gives best of both worlds.

