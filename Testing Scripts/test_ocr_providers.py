# =========================================================
# test_ocr_providers.py
# Unit and Integration Verification for Pluggable OCR Architecture
# =========================================================
import os
import sys
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PASSED = "[PASS]"
FAILED = "[FAIL]"
summary = []


def run_test(name, func):
    print(f"\n--- Running: {name} ---")
    try:
        func()
        print(f"  {PASSED}: {name}")
        summary.append((name, True))
    except Exception as e:
        print(f"  {FAILED}: {name} -> {e}")
        summary.append((name, False))


def test_factory_and_providers():
    from core.ocr import DocumentOCRFactory
    from core.ocr.mistral_provider import MistralOCRProvider
    from core.ocr.gemini_provider import GeminiOCRProvider
    from core.ocr.openai_provider import OpenAIOCRProvider

    providers = DocumentOCRFactory.list_available_providers()
    assert "mistral" in providers, "mistral not registered"
    assert "gemini" in providers, "gemini not registered"
    assert "openai" in providers, "openai not registered"


def test_pricing_and_costing():
    from core.ocr.base import OCRUsage
    from core.ocr.pricing import calculate_provider_cost

    # 1. Mistral (10 pages @ $0.001/page = $0.010 USD, INR = 0.865)
    u_mistral = OCRUsage(pages_processed=10, input_tokens=0, output_tokens=500)
    res_m = calculate_provider_cost("mistral", "mistral-ocr-3-0", u_mistral, usd_to_inr_rate=86.50)
    assert round(res_m.estimated_cost_usd, 4) == 0.0100
    assert round(res_m.estimated_cost_inr, 3) == 0.865

    # 2. Gemini (100,000 input @ $0.075/1M = $0.0075 + 10,000 output @ $0.30/1M = $0.003 -> $0.0105 USD)
    u_gemini = OCRUsage(pages_processed=5, input_tokens=100000, output_tokens=10000)
    res_g = calculate_provider_cost("gemini", "gemini-2.5-flash", u_gemini, usd_to_inr_rate=86.50)
    assert abs(res_g.estimated_cost_usd - 0.0105) < 1e-5
    assert abs(res_g.estimated_cost_inr - (0.0105 * 86.50)) < 1e-4


def test_mistral_table_embedding():
    from core.mistral_ocr_manager import blocks_to_markdown, ocr_json_to_markdown

    page_data = {
        "markdown": "# Bid Document\n\n[tbl-0.html](tbl-0.html)\n\nSection 2\n\n[tbl-1.html](tbl-1.html)",
        "tables": [
            {
                "id": "tbl-0.html",
                "content": "<table><tr><td>Bid Number</td><td>GEM/2026/B/99999</td></tr></table>"
            },
            {
                "id": "tbl-1.html",
                "content": "<table><tr><td>Officer</td><td>New Delhi</td></tr></table>"
            }
        ]
    }

    md = blocks_to_markdown(page_data)
    assert "[tbl-0.html](tbl-0.html)" not in md, "Placeholder was not replaced"
    assert "<table><tr><td>Bid Number</td><td>GEM/2026/B/99999</td></tr></table>" in md
    assert "<table><tr><td>Officer</td><td>New Delhi</td></tr></table>" in md

    # Full document multi-page stitch
    doc_data = {"pages": [page_data, {"markdown": "Page 2 content", "tables": []}]}
    full_md = ocr_json_to_markdown(doc_data)
    assert "\n\n---\n\n" in full_md
    assert "GEM/2026/B/99999" in full_md


def test_markdown_compatibility_with_parser():
    from core.parser import parse_bid_data

    sample_ocr_markdown = """
# Bid Document
<table>
  <tr><td>Bid End Date/Time</td><td>15-10-2026 18:00:00</td></tr>
  <tr><td>Bid Opening Date/Time</td><td>15-10-2026 18:30:00</td></tr>
  <tr><td>Ministry/State Name</td><td>Ministry of Defence</td></tr>
  <tr><td>Department Name</td><td>Department of Military Affairs</td></tr>
  <tr><td>Organisation Name</td><td>Indian Army</td></tr>
  <tr><td>Office Name</td><td>IHQ of MoD (Army)</td></tr>
  <tr><td>Total Quantity</td><td>100</td></tr>
  <tr><td>Item Category</td><td>Desktop Computers</td></tr>
</table>

## Buyer Added Bid Specific Additional Terms and Conditions
1. Experience Criteria: Bidder must have 3 years experience.
2. OEM Authorization Certificate is mandatory.
"""
    parsed = parse_bid_data(sample_ocr_markdown, product_type="Product")
    assert parsed.get("departments", {}).get("ministry_state_name") == "Ministry of Defence"
    assert parsed.get("departments", {}).get("department_name") == "Department of Military Affairs"
    assert parsed.get("timing", {}).get("bid_end_datetime") == "15-10-2026 18:00:00"
    assert "Experience Criteria" in parsed.get("terms", {}).get("buyer_atc", {}).get("generic", "")


def test_cache_resilience():
    from core.mistral_ocr_manager import cache

    test_key = "test_key_123"
    test_val = "cached_markdown_result"
    cache.set(test_key, test_val, timeout=60)
    assert cache.get(test_key) == test_val

    # Test atomic add
    assert cache.add(test_key, "new_val") is False  # Already exists
    cache.delete(test_key)
    assert cache.get(test_key) is None
    assert cache.add(test_key, "fresh_val") is True


if __name__ == "__main__":
    print("=" * 60)
    print("TEST SUITE: PLUGGABLE OCR ARCHITECTURE & MISTRAL ENGINE")
    print("=" * 60)

    run_test("1. Factory & Provider Instantiation", test_factory_and_providers)
    run_test("2. Centralized Price Catalog & Costing Engine", test_pricing_and_costing)
    run_test("3. Mistral HTML Table Substitution", test_mistral_table_embedding)
    run_test("4. Mistral Markdown -> core/parser.py Compatibility", test_markdown_compatibility_with_parser)
    run_test("5. In-Memory Cache Decoupling & Concurrency Lock", test_cache_resilience)

    print("\n" + "=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)
    all_ok = True
    for name, ok in summary:
        status_str = PASSED if ok else FAILED
        if not ok:
            all_ok = False
        print(f"  {status_str} : {name}")
    print("=" * 60)

    if all_ok:
        print("🎉 ALL OCR ARCHITECTURE TESTS PASSED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print("⚠️ SOME OCR TESTS FAILED!")
        sys.exit(1)
