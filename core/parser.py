# =========================================================
# core/parser.py
# PDF extraction + field parsing  +  card-HTML extraction
#
# IMPROVEMENTS (this revision):
#   1. New `get_card_details(card)` — pulls bid_no, FULL
#      item name (from popover `data-content`, NOT truncated),
#      quantity, department, dates straight from the listing
#      card HTML.  The popover content is the same text shown
#      on hover, e.g. for GEM/2026/B/7561028 it returns:
#        "Repair, Maintenance, and Installation of Plant/
#         Systems/Equipments (Version 2) - Industry Unit; Ele..."
#   2. Quantity / department / item are no longer truncated.
#   3. PDF parsing is kept as a *fallback* and for fields the
#      card does NOT show (estimated_value, bid_packet_type).
# =========================================================
import re
import os
import sys
import html
import fitz
from datetime import datetime
from config.settings import TESSERACT_CMD
from utils.logger import get_logger

log = get_logger("parser")

if sys.platform == "win32":
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    except ImportError:
        pass


# =========================================================
# PDF TEXT EXTRACTION
# =========================================================
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


def _strip_html(raw: str) -> str:
    """Strip HTML tags + decode entities. Popover data-content
    often contains <br>, &nbsp;, &amp; etc."""
    if not raw:
        return ""
    # Convert <br>, </p>, <li> etc. to spaces
    raw = re.sub(r"</?\s*(br|p|li|ul|ol|div|span)\b[^>]*>", " ", raw, flags=re.IGNORECASE)
    # Remove every remaining tag
    raw = re.sub(r"<[^>]+>", " ", raw)
    # Decode entities
    raw = html.unescape(raw)
    return clean_text(raw)


# =========================================================
# PDF FIELD PARSING (kept as fallback)
# =========================================================
def _extract_dates(pdf_text: str) -> tuple[str, str]:
    start_date = ""
    end_date = ""

    opening_match = re.search(
        r"(?:Bid\s+Opening\s+Date|Opening\s+Date|Bid\s+Opening)\s*(?:/|and)\s*Time\s+(\d{2}-\d{2}-\d{4})\s+(\d{2}:\d{2}:\d{2})",
        pdf_text, re.IGNORECASE,
    )
    if opening_match:
        start_date = f"{opening_match.group(1)} {opening_match.group(2)}"

    ending_match = re.search(
        r"(?:Bid\s+End\s+Date|End\s+Date|Bid\s+End)\s*(?:/|and)\s*Time\s+(\d{2}-\d{2}-\d{4})\s+(\d{2}:\d{2}:\d{2})",
        pdf_text, re.IGNORECASE,
    )
    if ending_match:
        end_date = f"{ending_match.group(1)} {ending_match.group(2)}"

    if not start_date or not end_date:
        all_dates = re.findall(
            r"(\d{2})-(\d{2})-(\d{4})\s+(\d{2}):(\d{2}):(\d{2})",
            pdf_text,
        )
        if all_dates:
            dates_list = []
            for day, month, year, hour, minute, second in all_dates:
                date_str = f"{day}-{month}-{year} {hour}:{minute}:{second}"
                try:
                    date_obj = datetime.strptime(date_str, "%d-%m-%Y %H:%M:%S")
                    dates_list.append((date_obj, date_str))
                except Exception:
                    pass
            if dates_list:
                dates_list.sort(key=lambda x: x[0])
                if not start_date:
                    start_date = dates_list[0][1]
                if not end_date:
                    end_date = dates_list[-1][1]

    return start_date, end_date


def parse_bid_data(pdf_text: str) -> dict:
    d = {}

    m = re.search(r"GEM/\d{4}/B/\d+", pdf_text)
    d["bid_no"] = m.group() if m else ""

    m = re.search(
        r"(?:Total Quantity|कुल मा\S*)\s*[:\-]?\s*([\d,]+)",
        pdf_text[:5000], re.IGNORECASE,
    )
    d["quantity"] = clean_text(m.group(1)) if m else ""

    item_candidates = []
    m = re.search(
        r"(?:व\S+\s+\S+\s*/Item Category|Item Category)\s+([^\n]{5,300})",
        pdf_text[:8000], re.IGNORECASE,
    )
    if m:
        val = m.group(1).strip()
        if "which regular" not in val.lower():
            item_candidates.append(val)

    m = re.search(
        r"Item Title\s*[:\-]?\s*([^\n]{5,300})",
        pdf_text[:8000], re.IGNORECASE,
    )
    if m:
        val = m.group(1).strip()
        if "which regular" not in val.lower():
            item_candidates.append(val)

    m = re.search(
        r"व\S+\s+\S+\s+([^\n/]{5,300})/",
        pdf_text[:8000],
    )
    if m:
        val = m.group(1).strip()
        if "which regular" not in val.lower():
            item_candidates.append(val)

    d["full_item_name"] = clean_text(item_candidates[0]) if item_candidates else ""

    m = re.search(
        r"(?:Department Name|विभाग का नाम|Department\s+(?:का|of))\s*[:\-]?\s*([^\n]{5,200})",
        pdf_text[:6000], re.IGNORECASE,
    )
    d["department"] = clean_text(m.group(1)) if m else ""

    start_date, end_date = _extract_dates(pdf_text)
    d["start_date"] = start_date
    d["end_date"] = end_date

    m = re.search(
        r"Estimated\s+Bid\s+Value\s+(\d[\d,\.]+)",
        pdf_text, re.IGNORECASE,
    )
    d["estimated_value"] = clean_text(m.group(1)) if m else ""

    m = re.search(
        r"Type of Bid\s+([\w][\w\s]+?)(?=\s{2,}|\s*(?:तकनीक|Primary|GEM/|\d{2}-\d{2}))",
        pdf_text, re.IGNORECASE,
    )
    d["bid_packet_type"] = clean_text(m.group(1)) if m else ""

    return d


# =========================================================
# CARD HTML — RA NUMBER
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
# CARD HTML — PRODUCT TYPE
# =========================================================
def get_product_type_from_card(card, bid_type_name: str) -> str:
    from config.settings import PRODUCT_TYPE_MAP
    try:
        text = card.inner_text()
        m = re.search(
            r"(?:Type\s*[:\-]\s*)(Product|Service|Works|Goods)",
            text, re.IGNORECASE,
        )
        if m:
            return m.group(1).title()
        for kw in ["Service", "Product", "Works", "Goods"]:
            if re.search(rf"\b{kw}\b", text, re.IGNORECASE):
                return kw.title()
    except Exception as e:
        log.debug(f"Product type card: {e}")
    return PRODUCT_TYPE_MAP.get(bid_type_name, bid_type_name)


# =========================================================
# CARD HTML — DATES
# =========================================================
def get_dates_from_card(card) -> tuple[str, str]:
    start_date = ""
    end_date = ""
    try:
        text = card.inner_text()

        start_m = re.search(
            r"Start\s+Date\s*[:\-]?\s*"
            r"(\d{2}-\d{2}-\d{4})\s+"
            r"(\d{1,2}:\d{2})\s*(AM|PM)?",
            text, re.IGNORECASE,
        )
        if start_m:
            date_part = start_m.group(1)
            time_part = _to_24h(start_m.group(2), start_m.group(3) or "")
            start_date = f"{date_part} {time_part}"

        end_m = re.search(
            r"End\s+Date\s*[:\-]?\s*"
            r"(\d{2}-\d{2}-\d{4})\s+"
            r"(\d{1,2}:\d{2})\s*(AM|PM)?",
            text, re.IGNORECASE,
        )
        if end_m:
            date_part = end_m.group(1)
            time_part = _to_24h(end_m.group(2), end_m.group(3) or "")
            end_date = f"{date_part} {time_part}"

    except Exception as e:
        log.debug(f"Card date scrape error: {e}")

    return start_date, end_date


def _to_24h(time_str: str, ampm: str) -> str:
    try:
        parts = time_str.strip().split(":")
        hour = int(parts[0])
        mins = int(parts[1]) if len(parts) > 1 else 0
        ampm = ampm.strip().upper()
        if ampm == "PM" and hour != 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0
        return f"{hour:02d}:{mins:02d}:00"
    except Exception:
        return f"{time_str}:00"


# =========================================================
# CARD HTML — FULL ITEM NAME from POPOVER
# =========================================================
# The GeM listing card looks like:
#   <p ...>Items: <a ... data-content="Repair, Maintenance, and
#          Installation of Plant/Systems/Equipments
#          (Version 2) - Industry Unit; Ele...">
#          Repair, Maintenance, and Insta...</a></p>
#
# `data-content` (or `data-original-title`) holds the FULL,
# untruncated string.  We prefer that over the visible text.
# =========================================================
_POPOVER_ATTRS = ("data-content", "data-original-title", "title")


def _read_popover_attr(node) -> str:
    """Try every popover-style attribute and return first hit."""
    for attr in _POPOVER_ATTRS:
        try:
            val = node.get_attribute(attr)
            if val and val.strip():
                return _strip_html(val)
        except Exception:
            continue
    return ""


def get_full_item_name_from_card(card) -> str:
    """
    Extract FULL item text from the popover on the card.

    Strategy:
      1. Find element whose visible text starts with 'Items:'
         and read its popover attribute.
      2. If not present, look for any descendant with a
         non-empty data-content / data-original-title / title.
      3. Fallback: parse 'Items:' line from card text.
    """
    try:
        # 1) the <a>/<p> that carries "Items:" usually owns the popover
        items_node = card.locator(
            "xpath=.//*[contains(translate(normalize-space(.), "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),"
            " 'items:')]"
        ).first
        if items_node and items_node.count() > 0:
            txt = _read_popover_attr(items_node)
            if txt:
                # popover sometimes echoes "Items: ..." — clean that off
                txt = re.sub(r"^\s*items?\s*:\s*", "", txt, flags=re.IGNORECASE)
                return txt

        # 2) any descendant with a popover attribute (broad sweep)
        for attr in _POPOVER_ATTRS:
            cand = card.locator(f"[{attr}]").first
            if cand and cand.count() > 0:
                val = cand.get_attribute(attr) or ""
                # Heuristic: must look like item list, not just an icon tooltip
                if val and len(val.strip()) > 15:
                    return _strip_html(val)
    except Exception as e:
        log.debug(f"Popover lookup failed: {e}")

    # 3) fallback — parse visible text
    try:
        text = card.inner_text()
        m = re.search(r"Items?\s*:\s*(.+?)(?:\n|Quantity\s*:)", text, re.IGNORECASE | re.DOTALL)
        if m:
            return clean_text(m.group(1)).rstrip(".")
    except Exception:
        pass
    return ""


# =========================================================
# CARD HTML — QUANTITY  (visible text on listing card)
# =========================================================
def get_quantity_from_card(card) -> str:
    try:
        text = card.inner_text()
        m = re.search(
            r"Quantity\s*[:\-]?\s*([\d][\d,]*)",
            text, re.IGNORECASE,
        )
        if m:
            return m.group(1).replace(",", "").strip()
    except Exception as e:
        log.debug(f"Quantity card scrape: {e}")
    return ""


# =========================================================
# CARD HTML — DEPARTMENT  (visible text on listing card)
# =========================================================
def get_department_from_card(card) -> str:
    try:
        text = card.inner_text()
        # Lines often read: "Department Name And Address:\n  <Dept>\n  <Address>"
        m = re.search(
            r"Department\s+Name(?:\s+And\s+Address)?\s*[:\-]?\s*\n?([^\n]{3,200})",
            text, re.IGNORECASE,
        )
        if m:
            return clean_text(m.group(1)).rstrip(",")
    except Exception as e:
        log.debug(f"Department card scrape: {e}")
    return ""


# =========================================================
# CARD HTML — BID NUMBER  (visible text on listing card)
# =========================================================
def get_bid_no_from_card(card) -> str:
    try:
        text = card.inner_text()
        m = re.search(r"GEM/\d{4}/B/\d+", text)
        return m.group() if m else ""
    except Exception:
        return ""


# =========================================================
# ONE-SHOT CARD DETAILS  (used by scraper)
# =========================================================
def get_card_details(card, bid_type_name: str) -> dict:
    """
    Return every field that is *reliably* available on the
    listing card.  This avoids relying on the PDF, which is
    inconsistent for item names / quantities.
    """
    start_date, end_date = get_dates_from_card(card)
    return {
        "bid_no":         get_bid_no_from_card(card),
        "ra_no":          get_ra_from_card(card),
        "product_type":   get_product_type_from_card(card, bid_type_name),
        "full_item_name": get_full_item_name_from_card(card),
        "quantity":       get_quantity_from_card(card),
        "department":     get_department_from_card(card),
        "start_date":     start_date,
        "end_date":       end_date,
    }