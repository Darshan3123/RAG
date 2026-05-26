# =========================================================
# core/parser.py
# PDF text extraction + field parsing
# =========================================================
import re
import os
import sys
import fitz
from config.settings import TESSERACT_CMD
from utils.logger import get_logger

log = get_logger("parser")

# Set Tesseract path only on Windows
if sys.platform == "win32":
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    except ImportError:
        pass


# =========================================================
# EXTRACT TEXT FROM PDF
# =========================================================
def extract_pdf_text(pdf_path: str) -> str:
    full_text = ""

    # --- PyMuPDF (fast, text PDFs) ---
    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            full_text += page.get_text()
        doc.close()
    except Exception as e:
        log.warning(f"PyMuPDF error: {e}")

    # --- OCR fallback (scanned/image PDFs) ---
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


# =========================================================
# CLEAN TEXT
# =========================================================
def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# =========================================================
# PARSE ALL FIELDS FROM PDF TEXT
# =========================================================
def parse_bid_data(pdf_text: str) -> dict:
    d = {}

    # --- Bid Number ---
    m = re.search(r"GEM/\d{4}/B/\d+", pdf_text)
    d["bid_no"] = m.group() if m else ""

    # --- Total Quantity ---
    m = re.search(
        r"(?:Total Quantity|Quantity\s*[:\-]?)\s*([\d,]+)",
        pdf_text, re.IGNORECASE
    )
    d["quantity"] = clean_text(m.group(1)) if m else ""

    # --- Item Name ---
    m = re.search(
        r"(?:Item Category|Item Title|Items?)\s*[/\w\s]*?\s+"
        r"([\w][\w\s\(\)\-,\.\/]+?)"
        r"(?=\s{2,}|\s*(?:Bid(?:der|No|Number|der's)"
        r"|GEM/|Quantity|Department|Ministry"
        r"|Start|End|MSE|MII|\d{2}-\d{2}-\d{4}))",
        pdf_text, re.IGNORECASE
    )
    if m:
        d["full_item_name"] = clean_text(m.group(1))
    else:
        m2 = re.search(
            r"(?:Item Category|Item Title|Items?)\s+([^\n]{3,80})",
            pdf_text, re.IGNORECASE
        )
        d["full_item_name"] = clean_text(m2.group(1)) if m2 else ""

    # --- Department ---
    m = re.search(
        r"Department(?:\s+(?:Name|का\s+नाम))?"
        r"(?:\s*/[^/\n]+)?\s+"
        r"([\w][\w\s\(\)\-,\.]+?)"
        r"(?=\s{2,}|\s*(?:Organisation|संगठन"
        r"|Office|काया|Ministry|मं|GEM/|\d))",
        pdf_text, re.IGNORECASE
    )
    if m:
        d["department"] = clean_text(m.group(1))
    else:
        m2 = re.search(
            r"Department Name\s+([^\n]{5,100})",
            pdf_text, re.IGNORECASE
        )
        d["department"] = clean_text(m2.group(1)) if m2 else ""

    # --- Bid End Date ---
    m = re.search(
        r"Bid\s+End\s+Date\s*/\s*Time\s+"
        r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2})",
        pdf_text, re.IGNORECASE
    )
    d["end_date"] = clean_text(m.group(1)) if m else ""

    # --- Bid Opening Date (start_date) ---
    m = re.search(
        r"Bid\s+Opening\s+Date\s*/\s*Time\s+"
        r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2})",
        pdf_text, re.IGNORECASE
    )
    d["start_date"] = clean_text(m.group(1)) if m else ""

    # --- Estimated Bid Value ---
    m = re.search(
        r"Estimated\s+Bid\s+Value\s+(\d[\d,\.]+)",
        pdf_text, re.IGNORECASE
    )
    d["estimated_value"] = clean_text(m.group(1)) if m else ""

    # --- Type of Bid (Two Packet / Single Packet) ---
    m = re.search(
        r"Type of Bid\s+([\w][\w\s]+?)"
        r"(?=\s{2,}|\s*(?:तकनीक|Primary|GEM/|\d{2}-\d{2}))",
        pdf_text, re.IGNORECASE
    )
    d["bid_packet_type"] = clean_text(m.group(1)) if m else ""

    return d


# =========================================================
# SCRAPE RA NUMBER FROM CARD HTML
# (lives on listing card, NOT in the PDF)
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
# Falls back to bid_type name mapping
# =========================================================
def get_product_type_from_card(card, bid_type_name: str) -> str:
    from config.settings import PRODUCT_TYPE_MAP
    try:
        text = card.inner_text()
        # explicit "Type: Product" label
        m = re.search(
            r"(?:Type\s*[:\-]\s*)(Product|Service|Works|Goods)",
            text, re.IGNORECASE
        )
        if m:
            return m.group(1).title()
        # standalone keyword
        for kw in ["Service", "Product", "Works", "Goods"]:
            if re.search(rf"\b{kw}\b", text, re.IGNORECASE):
                return kw.title()
    except Exception as e:
        log.debug(f"Product type card: {e}")
    return PRODUCT_TYPE_MAP.get(bid_type_name, bid_type_name)
