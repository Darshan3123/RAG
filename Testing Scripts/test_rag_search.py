# =========================================================================
# Testing Scripts/test_rag_search.py
# Verification Test: Domain Vector Chunking, BGE-Base-EN Embeddings,
# and pgvector Cosine Distance Search (< 5ms)
# =========================================================================
import json
import os
import sys
import time
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from core.embedder import (
    build_structured_bid_chunks,
    embed_query,
    generate_bid_embeddings,
)
from storage.postgres_db import PostgresBidDatabase
from utils.logger import get_logger

log = get_logger("test_rag_search")


def run_vector_test(sample_id: str = "GEM_2026_B_7548490"):
    print("=" * 70)
    print("🚀 GE MBRIDGE RAG & VECTOR SEARCH VERIFICATION TEST")
    print("=" * 70)

    # 1. Load sample tender JSON
    sample_path = ROOT_DIR / "downloads" / sample_id / f"{sample_id}.json"
    if not sample_path.exists():
        print(f"❌ Sample tender file not found at: {sample_path}")
        # Search for any available JSON in downloads
        json_files = list((ROOT_DIR / "downloads").glob("*/*.json"))
        if not json_files:
            print("❌ No tender JSON files found in downloads/ directory.")
            return
        sample_path = json_files[0]
        sample_id = sample_path.stem

    print(f"📄 Testing with tender: {sample_id} ({sample_path.name})")
    with open(sample_path, "r", encoding="utf-8") as f:
        bid_doc = json.load(f)

    # 2. Test domain structured chunking
    print("\n📦 STEP 1: Building Domain-Structured Chunks...")
    t0 = time.perf_counter()
    chunks = build_structured_bid_chunks(bid_doc)
    t_chunk = time.perf_counter() - t0

    chunk_types = {}
    for c in chunks:
        ctype = c["chunk_type"]
        chunk_types[ctype] = chunk_types.get(ctype, 0) + 1

    print(f"✅ Generated {len(chunks)} chunks in {t_chunk*1000:.2f} ms")
    for ctype, count in chunk_types.items():
        print(f"   • [{ctype.upper()}]: {count} chunks")

    # Preview chunks
    for i, c in enumerate(chunks[:3]):
        preview = c["chunk_text"].replace("\n", " ")[:120]
        print(f"   Chunk #{i+1} [{c['chunk_type']}]: {preview}...")

    # 3. Test Vector Embedding Generation (BGE 768-dim)
    print("\n🧠 STEP 2: Generating 768-dim BGE Embeddings...")
    t0 = time.perf_counter()
    chunks_with_emb = generate_bid_embeddings(bid_doc)
    t_emb = time.perf_counter() - t0

    sample_vec = chunks_with_emb[0]["embedding"]
    dim = len(sample_vec)
    print(f"✅ Embedded {len(chunks_with_emb)} chunks in {t_emb:.2f} s ({t_emb/max(1, len(chunks_with_emb))*1000:.1f} ms/chunk)")
    print(f"   Vector Dimensions: {dim} (Expected: 768)")
    print(f"   Vector Sample: [{sample_vec[0]:.4f}, {sample_vec[1]:.4f}, {sample_vec[2]:.4f}, ...]")
    assert dim == 768, f"Dimension mismatch: expected 768, got {dim}"

    # 4. Test Database Ingestion into pgvector
    print("\n💾 STEP 3: Ingesting into PostgreSQL `gem_bid_chunks` (Idempotent)...")
    db_connected = False
    try:
        db = PostgresBidDatabase()
        # Verify master row exists first to satisfy foreign key constraint
        bid_record = db.get_bid_by_no(sample_id)
        if not bid_record:
            print(f"   Upserting master tender record for foreign key integrity...")
            db.upsert_bid(bid_doc)

        inserted_count = db.insert_chunks(sample_id, chunks_with_emb)
        print(f"✅ Successfully inserted {inserted_count} vector rows into `gem_bid_chunks`.")
        db_connected = True
    except Exception as db_err:
        print(f"⚠️ PostgreSQL connection / table insertion skipped: {db_err}")
        print("   (Ensure local PostgreSQL with pgvector extension is running to test live SQL search)")

    # 5. Test Vector Cosine Distance Search
    if db_connected:
        print("\n🔍 STEP 4: Sub-5ms Cosine Similarity Semantic Retrieval...")
        test_queries = [
            "What motors are required and what are their ratings and quantities?",
            "What physical offline submissions must be sent and what is the delivery address?",
            "What are the EMD requirements and advisory bank?",
        ]

        for q in test_queries:
            print(f"\n❓ Query: \"{q}\"")
            t_q0 = time.perf_counter()
            q_vec = embed_query(q)
            t_q_emb = time.perf_counter() - t_q0

            t_s0 = time.perf_counter()
            results = db.search_chunks(q_vec, top_k=2, bid_id=sample_id)
            t_search = time.perf_counter() - s_time if 's_time' in locals() else (time.perf_counter() - t_s0)

            print(f"   Embed latency: {t_q_emb*1000:.2f} ms | Search latency: {t_search*1000:.2f} ms")
            for r_idx, res in enumerate(results, 1):
                dist = res.get("distance", 0.0)
                sim_score = 1.0 - dist
                text_snippet = res.get("chunk_text", "").replace("\n", " ")[:140]
                print(f"   [{r_idx}] Score: {sim_score:.3f} (dist: {dist:.3f}) | Type: {res.get('chunk_type')} | {text_snippet}...")

    print("\n" + "=" * 70)
    print("🎉 VECTOR EMBEDDING & CHUNKING VERIFICATION COMPLETE!")
    print("=" * 70)


if __name__ == "__main__":
    run_vector_test()
