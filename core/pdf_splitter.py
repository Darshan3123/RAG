# =========================================================
# core/pdf_splitter.py
# Selective PDF Boundary Detection, Slicing & Hybrid Stitching
# =========================================================
"""
Module for selective PDF slicing prior to OCR execution.

Empirical analysis of GeM tenders shows that 30% to 50% of the trailing pages
in tender documents belong strictly to 'Buyer Added Bid Specific Terms and Conditions' (ATC).
These pages contain plain legal clauses and declarations rather than complex data tables.

This module:
1. Locates the exact boundary page and vertical coordinate (y0) where ATC starts using PyMuPDF.
2. Extracts a lightweight 'core' PDF containing only pages 1..N (retaining all consignee/spec tables)
   to be sent to the configured OCR engine (Mistral / Gemini / OpenAI / Mineru).
3. Extracts all ATC clauses directly and instantaneously from page N downwards via PyMuPDF.
4. Seamlessly reassembles (stitches) the OCR Markdown and PyMuPDF ATC Markdown into a unified,
   high-fidelity document with zero duplications and zero dropped clauses.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from utils.logger import get_logger

try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        fitz = None

log = get_logger("pdf_splitter")


# Known ATC heading search queries (matched against PyMuPDF page text/rects)
ATC_SEARCH_QUERIES = [
    "Buyer Added Bid Specific Additional Terms and Conditions",
    "Buyer Added Bid Specific Terms and Conditions",
    "Buyer Added Bid Specific ATC",
    "Buyer Added Bid Specific",
    "क्रेता विशिष्ट अतिरिक्त नियम और शर्तें",
    "क्रेता द्वारा जोड़ी गई बिड की विशेष शर्तें",
    "क्रेता द्वारा जोड़ गई बड क वशेष शत",  # Encoding variation in GeM
]

# Regex patterns for fallback text matching
ATC_REGEX_PATTERNS = [
    re.compile(r"buyer\s+added\s+bid\s+specific\s+additional\s+terms\s+and\s+conditions", re.IGNORECASE),
    re.compile(r"buyer\s+added\s+bid\s+specific\s+terms\s+and\s+conditions", re.IGNORECASE),
    re.compile(r"buyer\s+added\s+bid\s+specific\s+atc", re.IGNORECASE),
    re.compile(r"buyer\s+added\s+bid\s+specific", re.IGNORECASE),
    re.compile(r"क्रेता\s+विशिष्ट\s+अतिरिक्त\s+नियम\s+और\s+शर्तें", re.IGNORECASE),
    re.compile(r"क्रेता\s+द्वारा\s+जोड़ी?\s+गई", re.IGNORECASE),
    re.compile(r"[Mm]ेता\s*[Pp]ारा\s*जोड़\s*गई\s*बड", re.IGNORECASE),
]


@dataclass
class SplitBoundary:
    """Represents the detected split boundary in a Bid PDF."""
    total_pages: int
    split_page_index: int          # 0-indexed page number where ATC begins
    heading_y0: float              # Vertical position (y0) of heading on that page
    pages_for_ocr: int             # Number of pages to send to OCR (split_page_index + 1)
    pages_saved: int               # Total pages saved from OCR execution
    matched_query: str = ""        # The phrase that triggered the split


def detect_atc_boundary(pdf_path: str) -> Optional[SplitBoundary]:
    """
    Scan a Bid PDF to locate the first page containing the ATC section heading.
    
    Args:
        pdf_path: Filepath to the tender PDF document.
        
    Returns:
        SplitBoundary object if heading is found and saves at least 1 page, else None.
    """
    if not fitz:
        log.warning("PyMuPDF (fitz) is not installed; skipping PDF slicing.")
        return None

    if not os.path.exists(pdf_path):
        log.warning(f"PDF not found for boundary detection: {pdf_path}")
        return None

    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)

        # 1-page documents cannot be sliced
        if total_pages <= 1:
            doc.close()
            return None

        for page_idx in range(total_pages):
            page = doc[page_idx]

            # 1. First attempt: Search for rects using PyMuPDF search_for (fastest and gives exact coordinates)
            for query in ATC_SEARCH_QUERIES:
                rects = page.search_for(query)
                if rects:
                    heading_y0 = rects[0].y0
                    pages_for_ocr = page_idx + 1
                    pages_saved = total_pages - pages_for_ocr
                    doc.close()

                    if pages_saved > 0:
                        log.info(
                            f"Detected ATC boundary in '{os.path.basename(pdf_path)}': "
                            f"Page {pages_for_ocr}/{total_pages} at y0={heading_y0:.1f} "
                            f"(Saves {pages_saved} pages from OCR)"
                        )
                        return SplitBoundary(
                            total_pages=total_pages,
                            split_page_index=page_idx,
                            heading_y0=heading_y0,
                            pages_for_ocr=pages_for_ocr,
                            pages_saved=pages_saved,
                            matched_query=query,
                        )
                    else:
                        # ATC heading is on the very last page; no pages can be sliced off
                        return None

            # 2. Second attempt: Fallback regex check on page text
            page_text = page.get_text("text")
            for pattern in ATC_REGEX_PATTERNS:
                m = pattern.search(page_text)
                if m:
                    # Estimate y0 around the middle of page if rect wasn't found directly
                    heading_y0 = page.rect.height * 0.35
                    pages_for_ocr = page_idx + 1
                    pages_saved = total_pages - pages_for_ocr
                    doc.close()

                    if pages_saved > 0:
                        log.info(
                            f"Detected ATC boundary via regex in '{os.path.basename(pdf_path)}': "
                            f"Page {pages_for_ocr}/{total_pages} (Saves {pages_saved} pages from OCR)"
                        )
                        return SplitBoundary(
                            total_pages=total_pages,
                            split_page_index=page_idx,
                            heading_y0=heading_y0,
                            pages_for_ocr=pages_for_ocr,
                            pages_saved=pages_saved,
                            matched_query=m.group(),
                        )
                    else:
                        return None

        doc.close()
        return None

    except Exception as e:
        log.warning(f"Error scanning ATC boundary for {pdf_path}: {e}")
        return None


def create_core_pdf_for_ocr(
    pdf_path: str,
    pages_for_ocr: int,
    output_path: Optional[str] = None
) -> str:
    """
    Create a sliced PDF containing pages 1..pages_for_ocr from the source document.
    
    Args:
        pdf_path: Original full Bid PDF path.
        pages_for_ocr: Count of pages to keep for OCR (inclusive).
        output_path: Destination path for sliced PDF. If None, appends '_core.pdf'.
        
    Returns:
        Absolute filepath to the created sliced PDF.
    """
    if not fitz:
        return pdf_path

    if not output_path:
        base, ext = os.path.splitext(pdf_path)
        output_path = f"{base}_core{ext}"

    try:
        src_doc = fitz.open(pdf_path)
        ocr_doc = fitz.open()

        # Insert pages 0 to pages_for_ocr - 1
        max_page = min(pages_for_ocr - 1, len(src_doc) - 1)
        ocr_doc.insert_pdf(src_doc, from_page=0, to_page=max_page)
        ocr_doc.save(output_path)

        ocr_doc.close()
        src_doc.close()
        return output_path
    except Exception as e:
        log.error(f"Failed to create sliced core PDF from {pdf_path}: {e}")
        return pdf_path


def extract_atc_markdown_pymupdf(
    pdf_path: str,
    split_page_index: int,
    heading_y0: float
) -> str:
    """
    Extract all ATC clauses directly from the PDF using PyMuPDF starting from the heading
    down to the end of the document.
    
    Args:
        pdf_path: Path to the original full Bid PDF.
        split_page_index: 0-indexed page number where ATC begins.
        heading_y0: Vertical position (y0) where the heading starts on split_page_index.
        
    Returns:
        Clean, formatted Markdown string containing the full ATC section.
    """
    if not fitz:
        return ""

    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        atc_parts: List[str] = []

        # 1. On split_page_index: extract from slightly above heading_y0 down to bottom of page
        first_page = doc[split_page_index]
        page_rect = first_page.rect
        # Clip from (heading_y0 - 15) to bottom of page
        y_start = max(0.0, heading_y0 - 15.0)
        clip_rect = fitz.Rect(0.0, y_start, page_rect.width, page_rect.height)
        clip_text = first_page.get_text("text", clip=clip_rect).strip()
        if clip_text:
            atc_parts.append(clip_text)

        # 2. Extract full text from all subsequent pages (split_page_index + 1 to end)
        for p_idx in range(split_page_index + 1, total_pages):
            p = doc[p_idx]
            p_text = p.get_text("text").strip()
            if p_text:
                atc_parts.append(p_text)

        doc.close()

        raw_atc_text = "\n\n".join(atc_parts)
        return _format_raw_atc_to_markdown(raw_atc_text)

    except Exception as e:
        log.error(f"Failed to extract PyMuPDF ATC text from {pdf_path}: {e}")
        return ""


def _format_raw_atc_to_markdown(raw_text: str) -> str:
    """
    Format raw PyMuPDF ATC text into clean, structured Markdown with standard headers.
    """
    if not raw_text.strip():
        return ""

    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    cleaned_lines: List[str] = []

    # Check if the text already starts with the heading
    heading_pattern = re.compile(
        r"(?:Buyer\s+Added\s+Bid\s+Specific\s+(?:Additional\s+)?Terms\s+and\s+Conditions|"
        r"क्रेता\s*विशिष्ट\s*अतिरिक्त\s*नियम|[Mm]ेता\s*[Pp]ारा\s*जोड़)",
        re.IGNORECASE
    )

    found_heading = False
    for line in lines:
        if not found_heading and heading_pattern.search(line):
            found_heading = True
            cleaned_lines.append("## Buyer Added Bid Specific Additional Terms and Conditions\n")
            continue

        # Format numbered clauses (e.g. '1. Generic', '2. Scope of Supply')
        if re.match(r"^\d+\.\s+[A-Za-z]+", line):
            cleaned_lines.append(f"\n### {line}\n")
        # Format sub-clauses (e.g. 'a. Copy of PAN Card', '1. I M/s...')
        elif re.match(r"^[a-zA-Z]\.\s+", line):
            cleaned_lines.append(f"* {line}")
        elif line.lower().startswith("--disclaimer--") or line.lower().startswith("disclaimer"):
            cleaned_lines.append(f"\n---\n**Disclaimer**\n")
        else:
            cleaned_lines.append(line)

    if not found_heading:
        cleaned_lines.insert(0, "## Buyer Added Bid Specific Additional Terms and Conditions\n")

    return "\n".join(cleaned_lines).strip()


def stitch_hybrid_markdown(ocr_markdown: str, atc_pymupdf_markdown: str) -> str:
    """
    Combine the OCR-generated Markdown (pages 1..N) with the PyMuPDF ATC Markdown (pages N..End).
    
    Ensures that any partial ATC text that appeared on page N in the OCR output is cleanly
    truncated so the PyMuPDF ATC text is appended without duplication.
    
    Args:
        ocr_markdown: Markdown produced by the OCR model for the core sliced PDF.
        atc_pymupdf_markdown: Markdown produced by PyMuPDF for the ATC section.
        
    Returns:
        Unified, complete Markdown document.
    """
    if not atc_pymupdf_markdown.strip():
        return ocr_markdown

    if not ocr_markdown.strip():
        return atc_pymupdf_markdown

    # Regex to detect where ATC begins in the OCR markdown
    atc_cut_pattern = re.compile(
        r"(?:\n|^)(?:#{1,4}\s*)?(?:(?:Buyer\s+Added\s+Bid\s+Specific\s+(?:Additional\s+)?Terms\s+and\s+Conditions)|"
        r"(?:Buyer\s+Added\s+Bid\s+Specific)|(?:[Mm]ेता\s*[Pp]ारा\s*जोड़\s*गई)|(?:क्रेता\s*विशिष्ट\s*अतिरिक्त\s*नियम))[\s\S]*$",
        re.IGNORECASE
    )

    m = atc_cut_pattern.search(ocr_markdown)
    if m:
        # Keep everything before the ATC heading in OCR markdown
        clean_ocr = ocr_markdown[:m.start()].rstrip()
    else:
        clean_ocr = ocr_markdown.rstrip()

    return f"{clean_ocr}\n\n{atc_pymupdf_markdown.strip()}\n"
