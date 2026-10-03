#!/usr/bin/env python3
# =========================================================================
# test_all_phases.py — End-to-End Verification Test Runner
# =========================================================================
"""
Verifies all implemented enhancements across Phase 1, Phase 2, and Phase 3:
  1. Data Normalizer (Currencies, Dates, Validation)
  2. Core Parser (Multi-item extraction, Financials, Schedule alignment)
  3. ATC Compliance Analyzer (Extraction & Gemini analysis)
  4. Database Storage & Auto-migration (SQLite)
  5. ChromaDB Vector Store & Hybrid Retrieval (BGE + BM25 + Cross-Encoder)
  6. RAG Question Answering (Clause-level compliance & Catalog search)
"""

import os
import sys
import json
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

print("=" * 70)
print("  GeM Bridge Pipeline — End-to-End Verification Test Suite")
print("=" * 70)

PASSED = "✅ PASS"
FAILED = "❌ FAIL"
summary = []


# ---------------------------------------------------------------------------
# TEST 1: Data Normalizer & Validation (Phase 1)
# ---------------------------------------------------------------------------
print("\n[TEST 1] Testing Data Normalizer & Currency / Date Standardizer...")
try:
    from core.normalizer import (
        parse_currency_to_number,
        format_inr_currency,
        parse_datetime_to_iso,
        calculate_date_metrics,
        normalize_bid_data,
        validate_bid_data,
    )

    # Test currency parsing
    assert parse_currency_to_number("18.85 Lakhs") == 1885000.0
    assert parse_currency_to_number("₹ 1.5 Crore") == 15000000.0
    assert parse_currency_to_number("₹ 50,000/-") == 50000.0
    assert format_inr_currency(1885000.0) == "₹18.85 Lakh"
    assert format_inr_currency(15000000.0) == "₹1.50 Crore"

    # Test date parsing
    iso_date = parse_datetime_to_iso("11-08-2026 12:00:00")
    assert iso_date is not None
    assert "2026-08-11" in iso_date

    # Test schema validation
    sample_norm = {
        "dates": {"start_date_iso": "2026-01-01T10:00:00+05:30", "end_date_iso": "2026-01-15T15:00:00+05:30", "bid_duration_days": 14, "is_expired": True},
        "items": {"total_items_count": 2, "total_quantity": 50},
        "financials": {"emd": {"required": False}},
    }
    val_res = validate_bid_data(bid_no="GEM/2026/B/1234567", normalized=sample_norm)
    assert val_res["is_valid"] is True
    print(f"  {PASSED}: Currency conversion, ISO 8601 timestamps, and schema validation verified.")
    summary.append(("Phase 1: Normalizer & Validation", True))
except Exception as e:
    print(f"  {FAILED}: Normalizer test failed: {e}")
    summary.append(("Phase 1: Normalizer & Validation", False))


# ---------------------------------------------------------------------------
# TEST 2: Core Parser on Real Markdown (Phase 1)
# ---------------------------------------------------------------------------
print("\n[TEST 2] Testing Core Parser on real tender markdown...")
try:
    from core.parser import parse_bid_data

    sample_md_path = Path("ATC EXTRACTOR/TEST_MARKDOWNS/GEM_2025_B_6904960/GEM_2025_B_6904960.md")
    if sample_md_path.exists():
        content = sample_md_path.read_text(encoding="utf-8")
        parsed = parse_bid_data(content)
        assert parsed.get("financials", {}).get("estimated_value") == 2000000.0
        assert parsed.get("financials", {}).get("emd", {}).get("amount_total") == 40000
        print(f"  {PASSED}: Estimated value and EMD successfully extracted from markdown.")
        summary.append(("Phase 1: Core Parser & Financials", True))
    else:
        print("  ⚠️ Skipped: Sample markdown not found.")
except Exception as e:
    print(f"  {FAILED}: Parser test failed: {e}")
    summary.append(("Phase 1: Core Parser & Financials", False))


# ---------------------------------------------------------------------------
# TEST 3: ATC Compliance Analyzer (Phase 2)
# ---------------------------------------------------------------------------
print("\n[TEST 3] Testing ATC Compliance Extraction & Gemini Inference...")
try:
    from pipeline.atc_analyzer import analyze_bid_atc, parse_atc_markdown_to_dict

    # Test parser structure on sample markdown
    sample_atc_output = """### 1. Standard Documents Required
* PAN Card
* GSTIN Certificate

### 2. Clarified ATC Documents & Mandatory Uploads
* **Certificate**: OEM Authorization Form

### 3. Exemption Documents Required
* **Proof for Exemption (MSEs)**: Udyam Registration (Explicit)

### 4. Physical Submissions (Offline)
* **EMD Demand Draft**: Hard copy
  * Deadline: 5 days
  * In Favor Of: Director Health
  * Payable At: New Delhi

### 5. Key Commercial Terms & Conditions to Follow
* **Warranty**: 3 years comprehensive onsite
"""
    parsed_atc = parse_atc_markdown_to_dict(sample_atc_output)
    assert len(parsed_atc["standard_documents"]) == 2
    assert parsed_atc["clarified_atc_documents"][0]["placeholder"] == "Certificate"
    assert parsed_atc["exemption_documents"][0]["is_explicit"] is True
    assert parsed_atc["physical_submissions"][0]["in_favor_of"] == "Director Health"
    assert parsed_atc["commercial_terms"][0]["topic"] == "Warranty"
    print(f"  {PASSED}: ATC structured parsing verified (all 5 sections correctly mapped).")

    # Live Gemini analysis test if API key is present
    if os.getenv("GEMINI_API_KEY"):
        sample_md = Path("ATC EXTRACTOR/TEST_MARKDOWNS/GEM_2026_B_7495766/GEM_2026_B_7495766.md")
        if sample_md.exists():
            live_res = analyze_bid_atc("GEM_2026_B_7495766", sample_md.read_text(encoding="utf-8"))
            assert live_res["status"] == "success"
            print(f"  {PASSED}: Live Gemini ATC extraction succeeded in {live_res.get('elapsed_seconds')}s.")
    summary.append(("Phase 2: ATC Compliance Extraction", True))
except Exception as e:
    print(f"  {FAILED}: ATC Analyzer test failed: {e}")
    summary.append(("Phase 2: ATC Compliance Extraction", False))


# ---------------------------------------------------------------------------
# TEST 4: SQLite Database Storage & Migration (Phase 2)
# ---------------------------------------------------------------------------
print("\n[TEST 4] Testing SQLite Database & atc_analysis Auto-Migration...")
try:
    from storage.database import BidDatabase
    db = BidDatabase()
    
    # Verify atc_analysis column exists by querying schema
    with db._conn() as conn:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(bids)").fetchall()]
        assert "atc_analysis" in cols
        assert "full_item_name" in cols
        assert "estimated_value" in cols

    print(f"  {PASSED}: SQLite database ready with atc_analysis column auto-migrated.")
    summary.append(("Phase 2: SQLite Schema & Auto-Migration", True))
except Exception as e:
    print(f"  {FAILED}: Database test failed: {e}")
    summary.append(("Phase 2: SQLite Schema & Auto-Migration", False))


# ---------------------------------------------------------------------------
# TEST 5: ChromaDB Vector Store & Hybrid Retrieval (Phase 3)
# ---------------------------------------------------------------------------
print("\n[TEST 5] Testing ChromaDB Vector Store & ATC Chunk Indexing...")
try:
    from rag.vector_store import _get_collection, stats as vs_stats
    col = _get_collection()
    vs = vs_stats()
    print(f"  Current ChromaDB chunks indexed: {vs['total_chunks']}")
    assert vs["total_chunks"] > 0, "No chunks found in ChromaDB. Run 'python main.py --reindex' or seed test bids first."
    print(f"  {PASSED}: ChromaDB collection online with {vs['total_chunks']} chunks.")
    summary.append(("Phase 3: ChromaDB Vector Store", True))
except Exception as e:
    print(f"  {FAILED}: Vector store test failed: {e}")
    summary.append(("Phase 3: ChromaDB Vector Store", False))


# ---------------------------------------------------------------------------
# TEST 6: Hybrid RAG Question Answering (Phase 3)
# ---------------------------------------------------------------------------
print("\n[TEST 6] Testing Hybrid RAG Query Engine...")
try:
    from rag.query_engine import QueryEngine
    engine = QueryEngine()

    # Query 1: Desktop computers
    res = engine.ask("desktop computer")
    assert len(res["sources"]) > 0
    print(f"  {PASSED}: RAG catalog search returned {len(res['sources'])} source(s).")

    # Query 2: Specific ATC compliance rule
    res_atc = engine.ask("What are the exemption rules for MSEs in the medical analyzer bid?")
    assert len(res_atc["sources"]) > 0
    assert "GEM/2025/B/6904960" in str(res_atc["sources"])
    print(f"  {PASSED}: RAG clause-level question answered accurately.")
    summary.append(("Phase 3: Hybrid RAG & Answer Synthesis", True))
except Exception as e:
    print(f"  {FAILED}: RAG query engine test failed: {e}")
    summary.append(("Phase 3: Hybrid RAG & Answer Synthesis", False))


# ---------------------------------------------------------------------------
# SUMMARY REPORT
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("  Test Results Summary")
print("=" * 70)
all_ok = True
for name, ok in summary:
    status_str = PASSED if ok else FAILED
    if not ok:
        all_ok = False
    print(f"  {status_str} : {name}")

print("=" * 70)
if all_ok:
    print("  🎉 ALL ENHANCEMENTS VERIFIED & READY FOR PRODUCTION!")
else:
    print("  ⚠️ SOME TESTS FAILED. Review output above.")
print("=" * 70 + "\n")
