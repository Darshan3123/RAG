# =========================================================
# test_pdf_splitter.py
# Verification Suite for Selective PDF Slicing & Stitching
# =========================================================
"""
Unit & Integration Test Suite for Selective PDF Slicing:
1. Boundary Detection (detect_atc_boundary)
2. Sliced Core PDF Generation (create_core_pdf_for_ocr)
3. Direct PyMuPDF ATC Extraction (extract_atc_markdown_pymupdf)
4. Hybrid Markdown Stitching (stitch_hybrid_markdown)
5. Parser Compatibility (core/parser.py on stitched markdown)
6. Financial Savings Calculation (calculate_saved_cost)
"""

import os
import sys
import glob
from pathlib import Path

# Ensure UTF-8 output on Windows
sys.stdout.reconfigure(encoding="utf-8")

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from core.pdf_splitter import (
    detect_atc_boundary,
    create_core_pdf_for_ocr,
    extract_atc_markdown_pymupdf,
    stitch_hybrid_markdown,
    SplitBoundary,
)
from core.ocr.pricing import calculate_saved_cost
from core.parser import parse_bid_data


def get_sample_pdf() -> str:
    """Find a real sample PDF in the downloads folder."""
    pdfs = [p for p in glob.glob("downloads/*/*.pdf") if not p.endswith("_RA.pdf") and not p.endswith("_core.pdf")]
    if pdfs:
        # Prefer GEM_2026_B_7747876 or GEM_2026_B_7799073 if available
        for p in pdfs:
            if "7747876" in p or "7799073" in p or "7347328" in p:
                return p
        return pdfs[0]
    raise FileNotFoundError("No downloaded PDFs found in downloads/ directory to test.")


def test_1_boundary_detection():
    print("\n--- Running: 1. Boundary Detection ---")
    sample_pdf = get_sample_pdf()
    print(f"Testing on sample: {sample_pdf}")
    
    boundary = detect_atc_boundary(sample_pdf)
    assert boundary is not None, f"Expected boundary to be found in {sample_pdf}"
    assert boundary.total_pages > 0, "Total pages must be > 0"
    assert boundary.pages_for_ocr > 0, "Pages for OCR must be > 0"
    assert boundary.pages_saved > 0, "Expected at least 1 page saved"
    assert boundary.pages_for_ocr + boundary.pages_saved == boundary.total_pages
    
    print(f"  Total Pages: {boundary.total_pages}")
    print(f"  Pages for OCR: {boundary.pages_for_ocr}")
    print(f"  Pages Saved: {boundary.pages_saved}")
    print(f"  Heading Y0: {boundary.heading_y0:.1f}")
    print(f"  Matched Query: '{boundary.matched_query}'")
    print("  [PASS]: 1. Boundary Detection")


def test_2_physical_slicing():
    print("\n--- Running: 2. Core PDF Physical Slicing ---")
    sample_pdf = get_sample_pdf()
    boundary = detect_atc_boundary(sample_pdf)
    assert boundary is not None
    
    temp_core_path = "storage/test_temp_core.pdf"
    os.makedirs("storage", exist_ok=True)
    
    try:
        created_path = create_core_pdf_for_ocr(
            pdf_path=sample_pdf,
            pages_for_ocr=boundary.pages_for_ocr,
            output_path=temp_core_path
        )
        assert os.path.exists(created_path), "Sliced PDF file must exist"
        
        doc = fitz.open(created_path)
        actual_pages = len(doc)
        doc.close()
        
        assert actual_pages == boundary.pages_for_ocr, (
            f"Sliced PDF expected {boundary.pages_for_ocr} pages, got {actual_pages}"
        )
        print(f"  Source PDF pages: {boundary.total_pages}")
        print(f"  Sliced core PDF pages: {actual_pages} (Correct)")
        print("  [PASS]: 2. Core PDF Physical Slicing")
    finally:
        if os.path.exists(temp_core_path):
            os.remove(temp_core_path)


def test_3_pymupdf_atc_extraction():
    print("\n--- Running: 3. PyMuPDF ATC Markdown Extraction ---")
    sample_pdf = get_sample_pdf()
    boundary = detect_atc_boundary(sample_pdf)
    assert boundary is not None
    
    atc_md = extract_atc_markdown_pymupdf(
        pdf_path=sample_pdf,
        split_page_index=boundary.split_page_index,
        heading_y0=boundary.heading_y0
    )
    
    assert atc_md.strip(), "Extracted ATC markdown should not be empty"
    assert "## Buyer Added Bid Specific Additional Terms and Conditions" in atc_md, (
        "Must contain standard ATC markdown header"
    )
    # Check that it extracted clauses
    assert len(atc_md) > 200, f"Expected substantial ATC text, got length {len(atc_md)}"
    
    print(f"  Extracted ATC text length: {len(atc_md)} characters")
    sample_preview = atc_md[:250].replace('\n', ' ')
    print(f"  Preview: {sample_preview}...")
    print("  [PASS]: 3. PyMuPDF ATC Markdown Extraction")


def test_4_hybrid_markdown_stitching():
    print("\n--- Running: 4. Hybrid Markdown Stitching ---")
    ocr_mock = (
        "# Bid Details\n"
        "| Item | Qty |\n"
        "| Desktop Computer | 50 |\n\n"
        "## Consignees\n"
        "| S.No | Officer | Quantity |\n"
        "| 1 | Officer A | 50 |\n\n"
        "Buyer Added Bid Specific Terms and Conditions\n"
        "1. Generic - Partial line that was on the boundary page\n"
    )
    
    atc_mock = (
        "## Buyer Added Bid Specific Additional Terms and Conditions\n\n"
        "### 1. Generic\n"
        "Bidder financial standing: The bidder should not be bankrupt.\n\n"
        "### 2. Scope of Supply\n"
        "Scope of supply includes all accessories.\n"
    )
    
    stitched = stitch_hybrid_markdown(ocr_mock, atc_mock)
    
    # Verify that partial OCR ATC text was removed
    assert "Partial line that was on the boundary page" not in stitched, (
        "Partial ATC text from OCR output should be cleanly truncated"
    )
    # Verify that consignee table is preserved
    assert "## Consignees" in stitched
    assert "| 1 | Officer A | 50 |" in stitched
    # Verify full ATC section is present
    assert "## Buyer Added Bid Specific Additional Terms and Conditions" in stitched
    assert "### 2. Scope of Supply" in stitched
    
    print("  Successfully stitched simulated OCR tables + PyMuPDF ATC clauses")
    print("  [PASS]: 4. Hybrid Markdown Stitching")


def test_5_core_parser_compatibility():
    print("\n--- Running: 5. Core Parser Compatibility ---")
    sample_pdf = get_sample_pdf()
    boundary = detect_atc_boundary(sample_pdf)
    assert boundary is not None
    
    atc_md = extract_atc_markdown_pymupdf(
        pdf_path=sample_pdf,
        split_page_index=boundary.split_page_index,
        heading_y0=boundary.heading_y0
    )
    
    mock_ocr = (
        "# Bid Details\n"
        "Bid Number: GEM/2026/B/9999999\n"
        "Estimated Bid Value: 25.50 Lakhs\n"
        "Total Quantity: 100\n"
        "Item Category: Desktop Computer\n"
    )
    
    hybrid_md = stitch_hybrid_markdown(mock_ocr, atc_md)
    parsed = parse_bid_data(hybrid_md, "PRODUCT")
    
    assert isinstance(parsed, dict)
    assert parsed.get("terms") is not None, "Parsed dictionary must contain terms section"
    assert len(parsed["terms"]) > 0, "Parsed terms should contain extracted buyer terms"
    
    print(f"  Parsed terms key count: {len(parsed['terms'])}")
    print("  [PASS]: 5. Core Parser Compatibility")


def test_6_cost_savings_calculation():
    print("\n--- Running: 6. Cost Savings Calculation ---")
    savings_mistral = calculate_saved_cost("mistral", "mistral-ocr-3-0", pages_saved=5)
    assert savings_mistral["pages_saved"] == 5
    assert savings_mistral["saved_usd"] == 0.005, f"Expected 0.005, got {savings_mistral['saved_usd']}"
    assert savings_mistral["saved_inr"] == round(0.005 * 86.50, 4)
    
    print(f"  Mistral (5 pages saved): ${savings_mistral['saved_usd']:.4f} (₹{savings_mistral['saved_inr']:.2f})")
    print("  [PASS]: 6. Cost Savings Calculation")


def run_all_tests():
    print("=" * 60)
    print("TEST SUITE: SELECTIVE PDF SLICING & HYBRID OCR STITCHING")
    print("=" * 60)
    
    tests = [
        ("1. Boundary Detection", test_1_boundary_detection),
        ("2. Physical Slicing", test_2_physical_slicing),
        ("3. PyMuPDF ATC Extraction", test_3_pymupdf_atc_extraction),
        ("4. Hybrid Markdown Stitching", test_4_hybrid_markdown_stitching),
        ("5. Core Parser Compatibility", test_5_core_parser_compatibility),
        ("6. Cost Savings Calculation", test_6_cost_savings_calculation),
    ]
    
    passed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"  [FAIL]: {name} -> {e}")
            import traceback
            traceback.print_exc()
            
    print("\n" + "=" * 60)
    print(f"TEST RESULTS: {passed}/{len(tests)} PASSED")
    print("=" * 60)
    if passed == len(tests):
        print("🎉 ALL PDF SLICING & HYBRID STITCHING TESTS PASSED!")
    else:
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()
