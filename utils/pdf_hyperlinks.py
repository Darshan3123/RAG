# =========================================================
# utils/pdf_hyperlinks.py
# PyMuPDF-based hyperlink extractor for GeM bid PDFs.
#
# Two public functions:
#   extract_hyperlinks(pdf_path)
#       → reads every page of the PDF, pulls all URI links,
#         resolves the anchor text from the bounding box,
#         returns a list of dicts:
#         [{"page": 1, "text": "...", "url": "...", "source": "bid"}]
#
#   inject_hyperlinks_into_markdown(md_text, hyperlinks)
#       → optionally appends a "## Hyperlinks" section to the
#         bottom of the Markdown so the URLs survive the text
#         pipeline and are searchable in RAG.
#         (The canonical store is the JSON hyperlinks[] field;
#          this is an optional text enrichment.)
# =========================================================
from __future__ import annotations
import re
from utils.logger import get_logger

log = get_logger("pdf_hyperlinks")


# ---------------------------------------------------------
# EXTRACT
# ---------------------------------------------------------
def extract_hyperlinks(pdf_path: str, source: str = "bid") -> list[dict]:
    """
    Extract all clickable URI hyperlinks from a PDF file using PyMuPDF.

    For each link the function also grabs the visible anchor text that
    sits inside the link rectangle on the page. If the rectangle
    contains no text (e.g. the whole page is one invisible link) the
    text field is set to the empty string.

    Args:
        pdf_path (str): Absolute or relative path to the PDF file.
        source   (str): Label stored in every record ("bid" / "ra").

    Returns:
        list[dict]: Deduplicated list ordered by page then position.
                    Each dict has keys: page, text, url, source.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        log.warning(
            "PyMuPDF (fitz) is not installed — hyperlink extraction skipped. "
            "Run: pip install pymupdf"
        )
        return []

    results: list[dict] = []
    seen_urls: set[str] = set()          # deduplicate identical URLs

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        log.warning(f"PyMuPDF could not open '{pdf_path}': {e}")
        return []

    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            links = page.get_links()

            for link in links:
                uri = link.get("uri", "").strip()
                if not uri:
                    continue

                # --- anchor text from bounding rect ---
                rect = link.get("from")
                if rect:
                    try:
                        text = page.get_textbox(rect).strip()
                    except Exception:
                        text = ""
                else:
                    text = ""

                # normalise whitespace in anchor text
                text = re.sub(r"\s+", " ", text)

                # skip pure-duplicate URLs (keep first occurrence)
                if uri in seen_urls:
                    continue
                seen_urls.add(uri)

                results.append({
                    "page":   page_num + 1,
                    "text":   text,
                    "url":    uri,
                    "source": source,
                })
    except Exception as e:
        log.error(f"Error while reading links from '{pdf_path}': {e}")
    finally:
        doc.close()

    log.info(f"Extracted {len(results)} unique hyperlinks from '{pdf_path}'")
    return results


# ---------------------------------------------------------
# INJECT INTO MARKDOWN  (optional enrichment)
# ---------------------------------------------------------
def inject_hyperlinks_into_markdown(md_text: str, hyperlinks: list[dict]) -> str:
    """
    Append a structured hyperlinks section to the end of a Markdown
    document so URLs are preserved in the text and become searchable
    through BM25 / dense retrieval in the RAG pipeline.

    The section is only appended when there are hyperlinks to add and
    the section does not already exist (idempotent).

    Format appended:
        ## Hyperlinks
        - [anchor text](url)  <!-- page N -->

    Args:
        md_text    (str):       Existing Markdown content.
        hyperlinks (list[dict]): Output of extract_hyperlinks().

    Returns:
        str: Markdown text with hyperlinks section appended (or original
             text unchanged if hyperlinks is empty or already present).
    """
    if not hyperlinks:
        return md_text

    # Idempotency guard — don't double-append
    if "## Hyperlinks" in md_text:
        return md_text

    lines = ["\n\n## Hyperlinks\n"]
    for item in hyperlinks:
        text  = item.get("text", "").strip() or item.get("url", "")
        url   = item.get("url", "")
        page  = item.get("page", "")
        # truncate very long anchor texts for readability
        display = (text[:120] + "…") if len(text) > 120 else text
        lines.append(f"- [{display}]({url})  <!-- page {page} -->")

    return md_text + "\n".join(lines)
