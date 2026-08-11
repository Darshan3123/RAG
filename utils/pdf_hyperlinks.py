# =========================================================
# utils/pdf_hyperlinks.py
# PyMuPDF-based hyperlink extractor for GeM bid PDFs.
#
# Two public functions:
#   extract_hyperlinks(pdf_path)
#       → reads every page of the PDF, pulls all URI links,
#         resolves the anchor text from the bounding box,
#         resolves a descriptive "name" label from the rest of
#         the line (e.g. "Buyer uploaded ATC document" for a
#         generic "Click here to view the file" anchor),
#         returns a list of dicts:
#         [{"page": 1, "name": "...", "text": "...", "url": "...", "source": "bid"}]
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
# Anchor texts that carry no information on their own
# (e.g. "Download" / "View" / "Click here to view the file")
# For these we go looking for a descriptive label elsewhere
# on the same line instead of storing the generic word.
# ---------------------------------------------------------
GENERIC_ANCHOR_TEXTS = {
    "",
    "download",
    "view",
    "here",
    "click here",
    "click here to view",
    "click here to view the file",
    "click here to download",
    "view file",
    "view document",
    "open",
    "link",
}

# Vertical tolerance (in PDF points) used when deciding whether two
# words sit on the "same line" as the link rectangle.
_LINE_Y_TOLERANCE = 2.0


def _is_generic_anchor(text: str) -> bool:
    """Return True if the anchor text is too generic to be useful on its own."""
    return re.sub(r"\s+", " ", text).strip().lower() in GENERIC_ANCHOR_TEXTS


def _get_preceding_line_label(page, rect) -> str:
    """
    Look at all words on the page that sit on the same horizontal line as
    the link rectangle `rect`, and return the ones that appear *before*
    the link (to its left) joined into a single label string.

    This recovers descriptive text such as "Buyer uploaded ATC document"
    that precedes a generic clickable phrase like "Click here to view
    the file", which sits outside the link's own bounding box and is
    therefore invisible to page.get_textbox(rect).

    Args:
        page: fitz.Page object.
        rect: fitz.Rect (or 4-tuple) — the link's "from" rectangle.

    Returns:
        str: Cleaned label text, or "" if nothing usable was found.
    """
    try:
        words = page.get_text("words")  # (x0, y0, x1, y1, word, block_no, line_no, word_no)
    except Exception:
        return ""

    if not words:
        return ""

    rect_y0, rect_y1 = rect.y0, rect.y1
    rect_x0 = rect.x0

    same_line_before = []
    for w in words:
        x0, y0, x1, y1, word = w[0], w[1], w[2], w[3], w[4]

        # word must vertically overlap the link's line (with tolerance)
        overlaps_line = (y0 <= rect_y1 + _LINE_Y_TOLERANCE) and (y1 >= rect_y0 - _LINE_Y_TOLERANCE)
        if not overlaps_line:
            continue

        # word must sit to the left of the link (i.e. comes before it)
        if x1 <= rect_x0 + 0.5:
            same_line_before.append((x0, word))

    if not same_line_before:
        return ""

    same_line_before.sort(key=lambda t: t[0])
    label = " ".join(w for _, w in same_line_before)

    # normalise whitespace and strip trailing separators like ":" or "-"
    label = re.sub(r"\s+", " ", label).strip()
    label = re.sub(r"[:\-–]\s*$", "", label).strip()

    return label


# ---------------------------------------------------------
# EXTRACT
# ---------------------------------------------------------
def extract_hyperlinks(pdf_path: str, source: str = "bid") -> list[dict]:
    """
    Extract all clickable URI hyperlinks from a PDF file using PyMuPDF.

    For each link the function grabs:
      - the visible anchor text inside the link rectangle ("text"), and
      - a descriptive "name" label. When the anchor text itself is
        generic (e.g. "Download", "View", "Click here to view the
        file"), the label is recovered from the rest of the same line,
        preceding the link (e.g. "Buyer uploaded ATC document"). When
        the anchor text is already descriptive, "name" simply mirrors
        it so downstream consumers always have a meaningful field to
        read regardless of anchor wording.

    Args:
        pdf_path (str): Absolute or relative path to the PDF file.
        source   (str): Label stored in every record ("bid" / "ra").

    Returns:
        list[dict]: Deduplicated list ordered by page then position.
                    Each dict has keys: page, name, text, url, source.
    """
    try:
        import pymupdf
    except ImportError:
        log.warning(
            "PyMuPDF (fitz) is not installed — hyperlink extraction skipped. "
            "Run: pip install pymupdf"
        )
        return []

    results: list[dict] = []
    seen_urls: set[str] = set()          # deduplicate identical URLs

    try:
        doc = pymupdf.open(pdf_path)
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

                # --- descriptive name/label ---
                name = text
                if rect and _is_generic_anchor(text):
                    label = _get_preceding_line_label(page, rect)
                    if label:
                        name = label

                # skip pure-duplicate URLs (keep first occurrence)
                if uri in seen_urls:
                    continue
                seen_urls.add(uri)

                results.append({
                    "page":   page_num + 1,
                    "name":   name,
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
        - **Name/Label**: [anchor text](url)  <!-- page N -->
        (the "**Name/Label**: " prefix is omitted when the name is
         empty or identical to the anchor text, to avoid repeating
         the same phrase twice)

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
        name  = item.get("name", "").strip()
        url   = item.get("url", "")
        page  = item.get("page", "")

        # truncate very long anchor texts for readability
        display = (text[:120] + "…") if len(text) > 120 else text

        if name and name.lower() != text.lower():
            prefix = f"**{name}**: "
        else:
            prefix = ""

        lines.append(f"- {prefix}[{display}]({url})  <!-- page {page} -->")

    return md_text + "\n".join(lines)