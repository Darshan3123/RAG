# =========================================================
# core/parser.py
# PDF extraction + field parsing
# FIX: Extract dates correctly (may span 2 different days)
# =========================================================
import re
import os
import sys
import fitz
from config.settings import TESSERACT_CMD
from utils.logger import get_logger

log = get_logger("parser")

if sys.platform == "win32":
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    except ImportError:
        pass


def extract_pdf_text(pdf_path: str) -> str:
    full_text = ""
    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            full_text += page.get_text()
        doc.close()
    except Exception as e:
        log.warning(f"PyMuPDF error: {e}")

    if len(full_text.strip()) < 100:
        log.info("Falling back to OCR...")
        try:
            from pdf2image import convert_from_path
            import pytesseract
            images = convert_from_path(pdf_path)
            for img in images:
                full_text += pytesseract.image_to_string(img)
        except Exception as e:
            log.warning(f"OCR error: {e}")

    return full_text


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# =========================================================
# PARSE ALL FIELDS FROM PDF TEXT
# FIX: Search entire PDF for dates (they may be far apart)
# =========================================================
def parse_bid_data(pdf_text: str) -> dict:
    d = {}

    # --- Bid Number ---
    m = re.search(r"GEM/\d{4}/B/\d+", pdf_text)
    d["bid_no"] = m.group() if m else ""

    # --- Total Quantity ---
    m = re.search(
        r"(?:Total Quantity|कुल मा\S*)\s*[:\-]?\s*([\d,]+)",
        pdf_text[:5000],
        re.IGNORECASE
    )
    d["quantity"] = clean_text(m.group(1)) if m else ""

    # --- Item Name / Item Category ---
    item_candidates = []
    
    m = re.search(
        r"(?:व\S+\s+\S+\s*/Item Category|Item Category)\s+([^\n]{5,120})",
        pdf_text[:8000],
        re.IGNORECASE
    )
    if m:
        val = m.group(1).strip()
        if "which regular" not in val.lower():
            item_candidates.append(val)
    
    m = re.search(
        r"Item Title\s*[:\-]?\s*([^\n]{5,100})",
        pdf_text[:8000],
        re.IGNORECASE
    )
    if m:
        val = m.group(1).strip()
        if "which regular" not in val.lower():
            item_candidates.append(val)
    
    m = re.search(
        r"व\S+\s+\S+\s+([^\n/]{5,100})/",
        pdf_text[:8000],
    )
    if m:
        val = m.group(1).strip()
        if "which regular" not in val.lower():
            item_candidates.append(val)

    d["full_item_name"] = clean_text(item_candidates[0]) if item_candidates else ""

    # --- Department ---
    m = re.search(
        r"(?:Department Name|विभाग का नाम|Department\s+(?:का|of))\s*[:\-]?\s*([^\n]{5,100})",
        pdf_text[:6000],
        re.IGNORECASE
    )
    d["department"] = clean_text(m.group(1)) if m else ""

    # --- DATES: FIX - Search ENTIRE PDF (dates may be far apart) ---
    # Look for "Bid End Date/Time" label with date
    # Pattern: "Bid End Date / Time" followed by DD-MM-YYYY HH:MM:SS
    end_date_match = re.search(
        r"Bid\s+End\s+Date\s*/\s*Time\s+(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2})",
        pdf_text,  # SEARCH ENTIRE PDF, not just first 10000
        re.IGNORECASE
    )
    d["end_date"] = clean_text(end_date_match.group(1)) if end_date_match else ""

    # Look for "Bid Opening Date/Time" label with date
    # May be on a DIFFERENT DATE than end_date
    start_date_match = re.search(
        r"Bid\s+Opening\s+Date\s*/\s*Time\s+(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2})",
        pdf_text,  # SEARCH ENTIRE PDF
        re.IGNORECASE
    )
    d["start_date"] = clean_text(start_date_match.group(1)) if start_date_match else ""

    # If labels not found, look for any two dates in chronological order
    # and assume first = opening, second = deadline
    if not d["start_date"] or not d["end_date"]:
        dates = re.findall(r"\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}", pdf_text)
        if len(dates) >= 2:
            if not d["start_date"]:
                d["start_date"] = dates[0]
            if not d["end_date"]:
                # Take the LAST date found (likely the end date)
                d["end_date"] = dates[-1]

    # --- Estimated Bid Value ---
    m = re.search(
        r"Estimated\s+Bid\s+Value\s+(\d[\d,\.]+)",
        pdf_text,  # Search entire PDF
        re.IGNORECASE
    )
    d["estimated_value"] = clean_text(m.group(1)) if m else ""

    # --- Type of Bid (Two Packet / Single Packet) ---
    m = re.search(
        r"Type of Bid\s+([\w][\w\s]+?)(?=\s{2,}|\s*(?:तकनीक|Primary|GEM/|\d{2}-\d{2}))",
        pdf_text,  # Search entire PDF
        re.IGNORECASE
    )
    d["bid_packet_type"] = clean_text(m.group(1)) if m else ""

    return d


# =========================================================
# SCRAPE RA NUMBER FROM CARD HTML
# =========================================================
def get_ra_from_card(card) -> str:
    try:
        text = card.inner_text()
        m = re.search(r"GEM/\d{4}/R/\d+", text)
        return m.group() if m else ""
    except Exception as e:
        log.debug(f"RA card scrape: {e}")
    return ""


# =========================================================
# SCRAPE PRODUCT TYPE FROM CARD HTML
# =========================================================
def get_product_type_from_card(card, bid_type_name: str) -> str:
    from config.settings import PRODUCT_TYPE_MAP
    try:
        text = card.inner_text()
        m = re.search(
            r"(?:Type\s*[:\-]\s*)(Product|Service|Works|Goods)",
            text,
            re.IGNORECASE
        )
        if m:
            return m.group(1).title()
        for kw in ["Service", "Product", "Works", "Goods"]:
            if re.search(rf"\b{kw}\b", text, re.IGNORECASE):
                return kw.title()
    except Exception as e:
        log.debug(f"Product type card: {e}")
    return PRODUCT_TYPE_MAP.get(bid_type_name, bid_type_name)