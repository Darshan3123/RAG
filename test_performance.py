#!/usr/bin/env python3
"""
Performance test script for GeM scraper
Tests individual components to identify bottlenecks
"""
import time
import sys
from pathlib import Path

def time_operation(name, func, *args, **kwargs):
    """Time a function and log the result"""
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"{'='*60}")
    start = time.time()
    try:
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        print(f"✓ {name} completed in {elapsed:.2f}s")
        return result, elapsed, None
    except Exception as e:
        elapsed = time.time() - start
        print(f"✗ {name} failed after {elapsed:.2f}s: {e}")
        return None, elapsed, str(e)

def test_pdf_extraction():
    """Test PDF text extraction"""
    from core.parser import extract_pdf_text
    import glob
    
    pdfs = glob.glob("downloads/*.pdf")[:3]  # Test first 3 PDFs
    if not pdfs:
        print("No PDFs found in downloads/")
        return
    
    for pdf in pdfs:
        pdf_name = Path(pdf).name
        result, elapsed, error = time_operation(
            f"Extract PDF: {pdf_name}",
            extract_pdf_text,
            pdf
        )
        if result:
            print(f"  Extracted {len(result)} characters")

def test_pdf_parsing():
    """Test PDF parsing"""
    from core.parser import extract_pdf_text, parse_bid_data, parse_bid_extended
    import glob
    
    pdfs = glob.glob("downloads/*.pdf")[:3]
    if not pdfs:
        print("No PDFs found in downloads/")
        return
    
    for pdf in pdfs:
        pdf_name = Path(pdf).name
        text = extract_pdf_text(pdf)
        
        # Test basic parsing
        result, elapsed, error = time_operation(
            f"Parse basic: {pdf_name}",
            parse_bid_data,
            text
        )
        
        # Test extended parsing
        result, elapsed, error = time_operation(
            f"Parse extended: {pdf_name}",
            parse_bid_extended,
            text,
            pdf
        )
        if result:
            print(f"  Extracted fields: {', '.join(k for k, v in result.items() if v)}")

def test_embedding_model():
    """Test embedding model loading and encoding"""
    from rag.embedder import embed_texts
    
    test_texts = [
        "Bid for supply of office stationery items including pens, paper, and folders",
        "Medical equipment procurement for government hospital",
        "Construction of new administrative building"
    ]
    
    # First call - loads model
    result, elapsed, error = time_operation(
        "Load embedding model (first call)",
        embed_texts,
        test_texts
    )
    if result:
        print(f"  Generated {len(result)} embeddings of dimension {len(result[0])}")
    
    # Second call - model cached
    result, elapsed, error = time_operation(
        "Encode texts (cached model)",
        embed_texts,
        test_texts * 5  # 15 texts
    )
    if result:
        print(f"  Generated {len(result)} embeddings")

def test_vector_store():
    """Test vector store operations"""
    from storage.database import BidDatabase
    
    result, elapsed, error = time_operation(
        "Connect to database",
        BidDatabase
    )
    
    if result:
        db = result
        stats = db.stats()
        print(f"  Total bids in DB: {stats['total']}")

def test_full_rag_pipeline():
    """Test complete RAG indexing for one bid"""
    from storage.database import BidDatabase
    
    db = BidDatabase()
    bids = db.get_all()
    
    if not bids:
        print("No bids in database")
        return
    
    # Get a bid
    test_bid = bids[0]
    bid_no = test_bid.get("bid_no", "unknown")
    
    # Remove from vector store first
    try:
        from rag.vector_store import _get_collection, _delete_bid_chunks
        col = _get_collection()
        _delete_bid_chunks(col, bid_no)
        print(f"Cleared existing chunks for {bid_no}")
    except Exception as e:
        print(f"Could not clear chunks: {e}")
    
    # Test RAG upsert
    result, elapsed, error = time_operation(
        f"RAG index bid: {bid_no}",
        lambda: __import__('rag.vector_store', fromlist=['upsert_bid']).upsert_bid(test_bid)
    )
    
    if error is None:
        print(f"  Successfully indexed {bid_no}")

def main():
    """Run all performance tests"""
    print("\n" + "="*60)
    print("GeM Scraper Performance Test Suite")
    print("="*60)
    
    results = {}
    
    # Test 1: PDF Extraction
    print("\n\n1. PDF TEXT EXTRACTION")
    test_pdf_extraction()
    
    # Test 2: PDF Parsing
    print("\n\n2. PDF PARSING")
    test_pdf_parsing()
    
    # Test 3: Database
    print("\n\n3. DATABASE CONNECTION")
    test_vector_store()
    
    # Test 4: Embedding Model
    print("\n\n4. EMBEDDING MODEL")
    test_embedding_model()
    
    # Test 5: Full RAG Pipeline
    print("\n\n5. FULL RAG PIPELINE")
    test_full_rag_pipeline()
    
    print("\n\n" + "="*60)
    print("Performance Test Complete")
    print("="*60)
    print("\nIf any operation took >30 seconds, that's your bottleneck.")
    print("Check the logs for detailed traces.")

if __name__ == "__main__":
    main()
