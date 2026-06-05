# GeM Tender Scraper - Debugging Guide

## Issue: Random Stalls During Scraping

### Root Cause Analysis

The scraper was getting stuck randomly during the parsing phase, which turned out to be related to the **RAG (Retrieval-Augmented Generation) indexing pipeline** that runs synchronously after each new bid is saved.

#### The Flow:
1. **Scraper** downloads and parses a bid
2. **Parser** extracts fields from PDF (can be slow for large/complex PDFs)
3. **Database** saves the bid
4. **RAG Indexing** (BLOCKING) happens immediately:
   - Loads the embedding model (first time only, but loads from disk)
   - Chunks the bid text
   - Embeds each chunk (CPU-intensive)
   - Stores in ChromaDB vector store

### Why It Appeared Random:
- **First bid** in each run: Loads the BGE embedding model (~400MB) into memory
- **Large PDFs**: Complex parsing with many regex operations
- **PDF content variation**: Some PDFs have more text requiring more chunks to embed
- **No timeout/logging**: When it stalled, there was no indication of where

## Improvements Made

### 1. Comprehensive Logging Added

#### Parser (core/parser.py)
```python
log.info("  [parser] Starting parse_bid_extended...")
log.info("  [parser] Base parsing complete")
log.info("  [parser] Extracting item category...")
log.info("  [parser] Determining procurement type...")
log.info("  [parser] Extracting authority...")
log.info("  [parser] Classifying sector...")
log.info("  [parser] Extracting EMD amount...")
log.info("  [parser] Extracting document cost...")
log.info("  [parser] Checking for corrigendum...")
log.info("  [parser] Extracting consignee details...")
log.info("  [parser] parse_bid_extended complete")
```

#### Scraper (pipeline/scraper.py)
```python
log.info(f"  Card {i+1}: PDF text extracted ({len(pdf_text)} chars)")
log.info(f"  Card {i+1}: basic parse complete, starting extended parse...")
log.info(f"  Card {i+1}: extended parse complete")
# Added try-except with full traceback logging
except Exception as parse_err:
    log.error(f"  Card {i+1}: PARSE ERROR - {parse_err}", exc_info=True)
```

#### Database (storage/database.py)
```python
log.info(f"  [database] Starting RAG indexing for {bid.get('bid_no')}...")
log.info(f"  [database] RAG indexing complete")
# Added exc_info=True for full stack traces
except Exception as e:
    log.warning(f"  [database] RAG index failed for {bid.get('bid_no','?')}: {e}", exc_info=True)
```

#### Vector Store (rag/vector_store.py)
```python
log.info(f"  [vector_store] Starting upsert for {bid_no}")
log.info(f"  [vector_store] Collection obtained")
log.info(f"  [vector_store] Built {len(chunks)} chunks")
log.info(f"  [vector_store] Deleted old chunks for {bid_no}")
log.info(f"  [vector_store] Embedding {len(chunks)} chunks...")
log.info(f"  [vector_store] Embeddings complete")
log.info(f"  [vector_store] Upserting to ChromaDB...")
log.info(f"  [vector_store] Upsert complete for {bid_no}")
```

#### Embedder (rag/embedder.py)
```python
log.info(f"  [embedder] Encoding {len(texts)} texts...")
log.info(f"  [embedder] Model loaded, starting encode...")
log.info(f"  [embedder] Encoding complete")
```

### 2. Error Handling Improvements

- All exceptions now include `exc_info=True` for full stack traces
- Parse errors are caught and logged without crashing the scraper
- RAG indexing failures are non-fatal (scraping continues)

## How to Monitor

### Normal Operation
Look for this pattern in the logs:
```
Card 1: reading card details...
Card 1: bid_no=GEM/2026/B/XXXXXXX
Card 1: extracting links...
Card 1: downloading PDF from https://...
Card 1: PDF download attempt 1/3: https://...
Card 1: Downloaded OK (HTTP): GeM-Bidding-XXXXXX.pdf
Card 1: extracting PDF text...
Card 1: PDF text extracted (12345 chars)
Card 1: parsing bid data...
  [parser] Starting parse_bid_extended...
  [parser] Base parsing complete
  [parser] Extracting item category...
  [parser] Category: Paper-Based Printing Services...
  [parser] Determining procurement type...
  [parser] Extracting authority...
  [parser] Authority: Department of Defense...
  [parser] Classifying sector...
  [parser] Extracting EMD amount...
  [parser] Extracting document cost...
  [parser] Checking for corrigendum...
  [parser] Extracting consignee details...
  [parser] Consignee city: New Delhi, state: Delhi
  [parser] parse_bid_extended complete
Card 1: basic parse complete, starting extended parse...
Card 1: extended parse complete
Card 1: assembling tender record...
Card 1: saving to database...
  NEW BID saved: GEM/2026/B/XXXXXXX
  [database] Starting RAG indexing for GEM/2026/B/XXXXXXX...
  [vector_store] Starting upsert for GEM/2026/B/XXXXXXX
  [vector_store] Collection obtained
  [vector_store] Built 15 chunks
  [vector_store] Deleted old chunks for GEM/2026/B/XXXXXXX
  [vector_store] Embedding 15 chunks...
  [embedder] Encoding 15 texts...
  [embedder] Model loaded, starting encode...
  [embedder] Encoding complete
  [vector_store] Embeddings complete
  [vector_store] Upserting to ChromaDB...
  [vector_store] Upsert complete for GEM/2026/B/XXXXXXX
  [database] RAG indexing complete
  [1/3] GEM/2026/B/XXXXXXX | Item: Paper-Based Printing Services... | Qty: 500 | NEW
```

### If It Stalls
The last log message will tell you exactly where:

- **Stuck after "Embedding X chunks..."**: The sentence transformer model is encoding (CPU-bound)
- **Stuck after "starting encode..."**: Model encoding in progress
- **Stuck after "PDF text extracted"**: Regex parsing is slow (complex PDF)
- **Stuck after "Extracting consignee details..."**: City/state matching over large dictionary

### Performance Bottlenecks

1. **First bid of each session**: ~5-20 seconds to load BGE model
2. **Each embedding operation**: ~1-5 seconds depending on chunk count
3. **Large PDFs**: More chunks = more embedding time
4. **Complex regex**: Authority/consignee extraction can be slow

## Recommendations

### Short-term
1. **Monitor logs**: The new logging will show exactly where delays occur
2. **Check CPU usage**: Embedding is CPU-intensive
3. **Check disk I/O**: First model load reads from disk

### Long-term Optimizations
1. **Async RAG indexing**: Move vector store updates to a background thread/queue
2. **Batch embedding**: Collect multiple bids before embedding
3. **Lazy model loading**: Only load embedding model when needed
4. **Timeout decorators**: Add timeouts to slow operations
5. **Progress bars**: Show progress during long operations

### Quick Test
Run with a single bid type and watch the logs:
```bash
python main.py --once
```

If it still stalls, the last log message will pinpoint the exact operation causing the delay.

## Log Files
All logs are written to:
- `logs/scraper.log` - Scraping operations
- `logs/parser.log` - PDF parsing details
- `logs/database.log` - Database operations
- `logs/vector_store.log` - RAG indexing
- `logs/embedder.log` - Embedding model operations
- `logs/main.log` - General application flow

Check these files for detailed trace information if the console output is insufficient.
