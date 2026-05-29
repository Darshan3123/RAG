# =========================================================
# core/parser.py
# PDF extraction + field parsing
# FIX: Extract dates correctly with better regex patterns
# =========================================================
import re
import os
import sys
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
# FIX: Extract dates with CORRECT order and labels
# =========================================================
def _extract_dates(pdf_text: str) -> tuple[str, str]:
    """
    Extract start_date and end_date from PDF.
    Look for explicit labels first:
    - "Bid Opening Date/Time" or "Bid Opening Date" → start_date
    - "Bid End Date/Time" or "Bid End Date" → end_date
    
    Returns: (start_date, end_date) as "DD-MM-YYYY HH:MM:SS"
    """
    start_date = ""
    end_date = ""
    
    # Pattern 1: Look for explicit "Bid Opening Date / Time" label
    # Label may appear with or without spaces around /
    opening_match = re.search(
        r"(?:Bid\s+Opening\s+Date|Opening\s+Date|Bid\s+Opening)\s*(?:/|and)\s*Time\s+(\d{2}-\d{2}-\d{4})\s+(\d{2}:\d{2}:\d{2})",
        pdf_text,
        re.IGNORECASE
    )
    if opening_match:
        start_date = f"{opening_match.group(1)} {opening_match.group(2)}"
        log.debug(f"Found opening date via label: {start_date}")
    
    # Pattern 2: Look for explicit "Bid End Date / Time" label
    ending_match = re.search(
        r"(?:Bid\s+End\s+Date|End\s+Date|Bid\s+End)\s*(?:/|and)\s*Time\s+(\d{2}-\d{2}-\d{4})\s+(\d{2}:\d{2}:\d{2})",
        pdf_text,
        re.IGNORECASE
    )
    if ending_match:
        end_date = f"{ending_match.group(1)} {ending_match.group(2)}"
        log.debug(f"Found end date via label: {end_date}")
    
    # If labels didn't work, try alternate patterns
    if not start_date or not end_date:
        # Find ALL dates in PDF
        all_dates = re.findall(
            r"(\d{2})-(\d{2})-(\d{4})\s+(\d{2}):(\d{2}):(\d{2})",
            pdf_text
        )
        
        if all_dates:
            log.debug(f"Found {len(all_dates)} dates in PDF")
            
            # Convert to comparable format
            dates_list = []
            for day, month, year, hour, minute, second in all_dates:
                date_str = f"{day}-{month}-{year} {hour}:{minute}:{second}"
                try:
                    date_obj = datetime.strptime(date_str, "%d-%m-%Y %H:%M:%S")
                    dates_list.append((date_obj, date_str))
                except:
                    pass
            
            if dates_list:
                # Sort by datetime
                dates_list.sort(key=lambda x: x[0])
                
                if not start_date and len(dates_list) > 0:
                    # First date = opening date (earliest)
                    start_date = dates_list[0][1]
                    log.debug(f"Using earliest date as opening: {start_date}")
                
                if not end_date and len(dates_list) > 0:
                    # Last date = end date (latest)
                    end_date = dates_list[-1][1]
                    log.debug(f"Using latest date as end: {end_date}")
    
    return start_date, end_date


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

    # --- DATES: Use fixed extraction function ---
    start_date, end_date = _extract_dates(pdf_text)
    d["start_date"] = start_date
    d["end_date"] = end_date

    # --- Estimated Bid Value ---
    m = re.search(
        r"Estimated\s+Bid\s+Value\s+(\d[\d,\.]+)",
        pdf_text,
        re.IGNORECASE
    )
    d["estimated_value"] = clean_text(m.group(1)) if m else ""

    # --- Type of Bid (Two Packet / Single Packet) ---
    m = re.search(
        r"Type of Bid\s+([\w][\w\s]+?)(?=\s{2,}|\s*(?:तकनीक|Primary|GEM/|\d{2}-\d{2}))",
        pdf_text,
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


# =========================================================
# SCRAPE DATES FROM CARD HTML (not from PDF)
# Portal card shows: "Start Date: DD-MM-YYYY HH:MM AM/PM"
#                    "End Date:   DD-MM-YYYY HH:MM AM/PM"
# =========================================================
def get_dates_from_card(card) -> tuple[str, str]:
    """
    Extract Start Date and End Date directly from the
    bid listing card on the GeM portal HTML.
    Returns: (start_date, end_date) as "DD-MM-YYYY HH:MM:SS"
    """
    start_date = ""
    end_date   = ""

    try:
        text = card.inner_text()

        # Match "Start Date: DD-MM-YYYY HH:MM AM/PM"
        start_m = re.search(
            r"Start\s+Date\s*[:\-]?\s*"
            r"(\d{2}-\d{2}-\d{4})\s+"
            r"(\d{1,2}:\d{2})\s*(AM|PM)?",
            text,
            re.IGNORECASE
        )
        if start_m:
            date_part = start_m.group(1)
            time_part = _to_24h(start_m.group(2), start_m.group(3) or "")
            start_date = f"{date_part} {time_part}"

        # Match "End Date: DD-MM-YYYY HH:MM AM/PM"
        end_m = re.search(
            r"End\s+Date\s*[:\-]?\s*"
            r"(\d{2}-\d{2}-\d{4})\s+"
            r"(\d{1,2}:\d{2})\s*(AM|PM)?",
            text,
            re.IGNORECASE
        )
        if end_m:
            date_part = end_m.group(1)
            time_part = _to_24h(end_m.group(2), end_m.group(3) or "")
            end_date = f"{date_part} {time_part}"

    except Exception as e:
        log.debug(f"Card date scrape error: {e}")

    return start_date, end_date


def _to_24h(time_str: str, ampm: str) -> str:
    """Convert '3:44 PM' → '15:44:00', '10:07 AM' → '10:07:00'"""
    try:
        parts = time_str.strip().split(":")
        hour  = int(parts[0])
        mins  = int(parts[1]) if len(parts) > 1 else 0
        ampm  = ampm.strip().upper()
        if ampm == "PM" and hour != 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0
        return f"{hour:02d}:{mins:02d}:00"
    except:
        return f"{time_str}:00"