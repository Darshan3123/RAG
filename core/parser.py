# =========================================================
# core/parser.py
# Mineru PDF Markdown field parsing + card-HTML extraction
#
# IMPLEMENTS VLM MARKDOWN SCHEMA:
# - Clean separation between HTML (Card) and PDF parsing.
# - Uses Mineru VLM engine output (Markdown/HTML) with BeautifulSoup
#   and structured regex extraction.
# =========================================================
import os
import re
import sys
import html
from typing import Optional
from bs4 import BeautifulSoup
from utils.logger import get_logger

log = get_logger("parser")

# ---------------------------------------------------------------------------
# Sentinel & Shared Helpers
# ---------------------------------------------------------------------------
_ABSENT = object()


def docling_first(d: dict, key: str, fallback_fn):
    """
    Retrieve a key from dictionary `d`. If missing or equal to sentinel `_ABSENT`,
    invoke `fallback_fn` as a fallback strategy.
    
    Args:
        d (dict): Dictionary to inspect.
        key (str): Key name to look up.
        fallback_fn (callable): Callback function executed if key is absent.
        
    Returns:
        Any: Value from dictionary or result of fallback_fn.
    """
    val = d.get(key, _ABSENT)
    return val if val is not _ABSENT else fallback_fn()


def clean_text(text: str) -> str:
    """
    Normalize raw text string by removing HTML break tags, newline characters, 
    and consolidating multiple spaces into a single space.
    
    Args:
        text (str): Input text string.
        
    Returns:
        str: Cleaned and trimmed string.
    """
    if not text:
        return ""
    text = re.sub(r'<br\s*/?>', ' ', str(text), flags=re.IGNORECASE)
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean(text) -> str:
    """
    Alias wrapper around `clean_text`.
    
    Args:
        text: Input string or object convertible to string.
        
    Returns:
        str: Cleaned string.
    """
    return clean_text(text)


def _strip_html(raw: str) -> str:
    """
    Strip HTML tags and unescape HTML entities, returning cleaned text.
    
    Args:
        raw (str): Raw string containing HTML elements.
        
    Returns:
        str: Plain text stripped of tags and unescaped.
    """
    if not raw:
        return ""
    raw = re.sub(r"</?\s*(br|p|li|ul|ol|div|span)\b[^>]*>", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return clean_text(raw)


def to_int(value) -> Optional[int]:
    """
    Extract all numeric digits from `value` and convert to an integer.
    
    Args:
        value: Input value (str/int/float).
        
    Returns:
        Optional[int]: Extracted integer or None if invalid/empty.
    """
    try:
        digits = re.sub(r"[^\d]", "", str(value))
        return int(digits) if digits else None
    except (ValueError, TypeError):
        return None


def to_float(value) -> Optional[float]:
    """
    Extract the first floating point decimal number matching pattern from `value`.
    
    Args:
        value: Input value (str/float/int).
        
    Returns:
        Optional[float]: Extracted float or None if invalid/empty.
    """
    try:
        m = re.search(r"[\d.]+", str(value))
        return float(m.group()) if m else None
    except (ValueError, TypeError):
        return None


def yesno(value) -> Optional[str]:
    """
    Normalize strings into standard 'Yes', 'No', or None representations.
    
    Args:
        value: String or value to evaluate.
        
    Returns:
        Optional[str]: 'Yes', 'No', or None.
    """
    v = clean(value).lower()
    if not v or v == "none":
        return None
    if v.startswith("yes"):
        return "Yes"
    if v.startswith("no"):
        return "No"
    return None


# ---------------------------------------------------------------------------
# Markdown Table Helpers
# ---------------------------------------------------------------------------
def md_table_kv(soup: BeautifulSoup) -> dict[str, str]:
    """
    Extract key-value pairs from HTML/Markdown 2-column tables in BeautifulSoup parsed document.
    
    Args:
        soup (BeautifulSoup): BeautifulSoup object of PDF HTML/Markdown content.
        
    Returns:
        dict[str, str]: Map of extracted key-value header/cell text pairs.
    """
    kv: dict[str, str] = {}
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) >= 2:
                key = clean(cells[0].get_text())
                val = clean(cells[1].get_text())
                if key:
                    kv[key] = val
    return kv


def md_get(kv: dict[str, str], *patterns: str) -> Optional[str]:
    """
    Look up a key in the extracted key-value map using case-insensitive substring search matching `patterns`.
    
    Args:
        kv (dict[str, str]): Key-value dictionary.
        *patterns (str): Variable list of search keyword patterns.
        
    Returns:
        Optional[str]: Value matching any pattern or None if not found.
    """
    lp = [p.lower() for p in patterns]
    for k, v in kv.items():
        kl = k.lower()
        for p in lp:
            if p in kl:
                return v
    return None


# ---------------------------------------------------------------------------
# Section 1 — Timing & Departments
# ---------------------------------------------------------------------------
def parse_pdf_section(docling: dict, kv: dict) -> tuple[dict, dict]:
    """
    Parse timing dates (end date, opening date, validity days) and department information 
    from parsed PDF structured dict or key-value table.
    
    Args:
        docling (dict): Parsed JSON dictionary.
        kv (dict): Extracted table key-value map.
        
    Returns:
        tuple[dict, dict]: (timing_dict, departments_dict).
    """
    timing = {
        "bid_end_datetime":
            md_get(kv, "Bid End Date/Time", "bid end date", "बिड बंद होने"),
        "bid_opening_datetime":
            md_get(kv, "Bid Opening Date/Time", "bid opening date", "बिड खुलने"),
        "bid_offer_validity_days":
            to_int(md_get(kv, "Bid Offer Validity", "बिड पेशकश वैधता") or ""),
    }
    d = docling.get("departments", {})
    departments = {
        "ministry_state_name": docling_first(
            d, "ministry_state_name",
            lambda: md_get(kv, "Ministry/State Name", "Ministry", "मंत्रालय")),
        "department_name": docling_first(
            d, "department_name",
            lambda: md_get(kv, "Department Name", "विभाग का नाम")),
        "organisation_name": docling_first(
            d, "organisation_name",
            lambda: md_get(kv, "Organisation Name", "संगठन का नाम")),
        "office_name": docling_first(
            d, "office_name",
            lambda: md_get(kv, "Office Name", "कार्यालय का नाम")),
    }
    return timing, departments


# ---------------------------------------------------------------------------
# Section 2 — Items
# ---------------------------------------------------------------------------
def parse_items_section(docling: dict, kv: dict, soup: BeautifulSoup = None) -> dict:
    """
    Parse item categories, quantities, and verify quantity match flags across 
    Docling JSON structures or BeautifulSoup HTML table fallback.
    
    Args:
        docling (dict): Parsed JSON dictionary.
        kv (dict): Table key-value map.
        soup (BeautifulSoup, optional): HTML soup for parsing tables when docling lacks items.
        
    Returns:
        dict: Extracted items dictionary with quantity match flag.
    """
    d = docling.get("items", {})
    total_qty = docling_first(
        d, "total_quantity_extracted",
        lambda: to_int(md_get(kv, "Total Quantity", "कुल मात्रा") or ""))
    result: dict = {
        "total_quantity_extracted": total_qty,
        "quantity_match_flag":      "No",
    }
    extracted_total = 0
    found_docling_items = False
    for key, val in d.items():
        if re.match(r"^item \d+$", key, re.IGNORECASE) and isinstance(val, dict):
            found_docling_items = True
            qty = val.get("quantity")
            result[key] = {
                "item_category": val.get("item_category", ""),
                "quantity":      val.get("quantity"),
            }
            try:
                extracted_total += int(qty) if qty is not None else 0
            except (TypeError, ValueError):
                pass

    if not found_docling_items:
        cat_raw = md_get(kv, "Item Category", "वस्तु श्रेणी") or ""
        names = [clean(x) for x in cat_raw.split(",") if clean(x)]
        
        item_quantities = []
        if soup:
            for table in soup.find_all("table"):
                rows = table.find_all("tr")
                if not rows:
                    continue
                hdr = " ".join(clean(td.get_text()) for td in rows[0].find_all(["td", "th"])).lower()
                
                if ("consignee" in hdr or "परेषिती" in hdr) and ("quantity" in hdr or "मात्रा" in hdr):
                    hdr_cells = [clean(td.get_text()).lower() for td in rows[0].find_all(["td", "th"])]
                    i_qty = next((i for i, h in enumerate(hdr_cells) if "quantity" in h or "मात्रा" in h), 3)
                    
                    tbl_qty = 0
                    for row in rows[1:]:
                        cells = [clean(td.get_text()) for td in row.find_all(["td", "th"])]
                        if i_qty < len(cells):
                            q = to_int(cells[i_qty])
                            if q: 
                                tbl_qty += q
                    item_quantities.append(tbl_qty)

        if len(names) == 1:
            result["item 1"] = {"item_category": names[0], "quantity": total_qty}
            if total_qty:
                extracted_total = total_qty
        elif names:
            if len(names) == len(item_quantities):
                for i, (name, qty) in enumerate(zip(names, item_quantities), start=1):
                    result[f"item {i}"] = {"item_category": name, "quantity": qty}
                    extracted_total += (qty or 0)
            else:
                for i, name in enumerate(names, start=1):
                    result[f"item {i}"] = {"item_category": name, "quantity": None}

    if total_qty and extracted_total > 0:
        result["quantity_match_flag"] = "Yes" if extracted_total == total_qty else "No"
    else:
        result["quantity_match_flag"] = d.get("quantity_match_flag", "No")
    return result


# ---------------------------------------------------------------------------
# Section 3 — Evaluation
# ---------------------------------------------------------------------------
def _find_table_by_headers(soup: BeautifulSoup, must_have: list[str],
                            must_not_have: list[str] | None = None):
    """
    Search BeautifulSoup document for a table matching specified header keywords.
    
    Args:
        soup (BeautifulSoup): HTML document tree.
        must_have (list[str]): List of keywords that header text MUST contain.
        must_not_have (list[str], optional): Keywords that header text MUST NOT contain.
        
    Returns:
        tuple: (rows_list, header_cells_list) or (None, None) if not found.
    """
    must_have     = [kw.lower() for kw in must_have]
    must_not_have = [kw.lower() for kw in (must_not_have or [])]
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_cells = [clean(td.get_text()) for td in rows[0].find_all(["td", "th"])]
        header_text = " ".join(header_cells).lower()
        if all(kw in header_text for kw in must_have) and \
           not any(kw in header_text for kw in must_not_have):
            return rows, header_cells
    return None, None


def _col_index(header_cells: list[str], *keywords: str) -> Optional[int]:
    """
    Find index of column whose header text matches any of the given keywords.
    
    Args:
        header_cells (list[str]): List of table column header titles.
        *keywords (str): Search keyword patterns.
        
    Returns:
        Optional[int]: 0-based column index or None if not found.
    """
    for i, h in enumerate(header_cells):
        hl = h.lower()
        if any(kw.lower() in hl for kw in keywords):
            return i
    return None


def _normalise_group_key(raw_key: str) -> str:
    """
    Standardize group/package schedule names into canonical 'Package N' format.
    
    Args:
        raw_key (str): Raw group or package header identifier.
        
    Returns:
        str: Normalized key (e.g. 'Package 1').
    """
    raw_key = str(raw_key).strip()
    if re.fullmatch(r"\d+", raw_key):
        return f"Package {int(raw_key)}"
    m = re.fullmatch(r"group\s+g0*(\d+)", raw_key, re.IGNORECASE)
    if m:
        return f"Package {int(m.group(1))}"
    return raw_key


def _cell_at(item_cells: list[tuple[str, int, int]], idx_in_full_row: int) -> str:
    """
    Safely retrieve text from row cell list taking offset into account.
    """
    adj = idx_in_full_row - 1
    return item_cells[adj][0] if 0 <= adj < len(item_cells) else ""


def _parse_group_wise_schedules(soup: BeautifulSoup) -> dict:
    """
    Parse group-wise/package-wise evaluation schedules from BeautifulSoup HTML tables.
    
    Args:
        soup (BeautifulSoup): Parsed HTML content.
        
    Returns:
        dict: Group/Package schedule mapping containing items and consignee/quantity details.
    """
    rows, header_cells = _find_table_by_headers(
        soup, must_have=["evaluation schedules"], must_not_have=[])
    if rows is None:
        return {}
    header_text = " ".join(header_cells).lower()
    if not any(kw in header_text for kw in ("consignee", "reporting", "officer")):
        return {} 

    idx_item     = _col_index(header_cells, "item/category", "item")
    idx_officer  = _col_index(header_cells, "consignee/reporting", "reporting officer", "consignee")
    idx_address  = _col_index(header_cells, "address")
    idx_quantity = _col_index(header_cells, "quantity")
    if idx_item     is None: idx_item     = 1
    if idx_officer  is None: idx_officer  = 2
    if idx_address  is None: idx_address  = 3
    if idx_quantity is None: idx_quantity = 4

    schedules: dict = {}
    current_group = None
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        cell_data = [
            (clean(c.get_text()), int(c.get("colspan", 1)), int(c.get("rowspan", 1)))
            for c in cells
        ]
        if cell_data and cell_data[0][2] > 1:
            group_name = cell_data[0][0]
            if group_name:
                current_group = _normalise_group_key(group_name)
                schedules.setdefault(current_group, {})
            item_cells = cell_data[1:]
        elif cell_data and re.match(r"^group\s+g\d+", cell_data[0][0], re.IGNORECASE):
            current_group = _normalise_group_key(cell_data[0][0])
            schedules.setdefault(current_group, {})
            item_cells = cell_data[1:]
        else:
            item_cells = cell_data

        if current_group is None or not item_cells:
            continue

        item_cat = _cell_at(item_cells, idx_item)
        officer  = _cell_at(item_cells, idx_officer)
        address  = _cell_at(item_cells, idx_address)
        quantity = _cell_at(item_cells, idx_quantity)
        if not item_cat or item_cat.lower() in ("item/category", "item", ""):
            continue

        item_no = len(schedules[current_group]) + 1
        schedules[current_group][f"Item_{item_no}"] = {
            "Item/Category":               item_cat,
            "Consignee/Reporting Officer": officer,
            "Consignee Address":           address,
            "Quantity":                    quantity,
        }
    return schedules


def _cell_val(cells: list, idx: int) -> str:
    """Safely return list element at index or empty string."""
    return cells[idx] if 0 <= idx < len(cells) else ""


def _parse_item_wise_schedules(soup: BeautifulSoup) -> dict:
    """
    Parse item-wise evaluation schedules from BeautifulSoup HTML tables.
    
    Args:
        soup (BeautifulSoup): Parsed HTML document.
        
    Returns:
        dict: Item-wise evaluation schedule map indexed by schedule number.
    """
    rows, header_cells = _find_table_by_headers(
        soup, must_have=["evaluation schedules"], must_not_have=[])
    if rows is None:
        return {}
    header_text = " ".join(header_cells).lower()
    if any(kw in header_text for kw in ("consignee", "reporting", "officer")):
        return {}
    if not any(kw in header_text for kw in ("estimated value", "अनुमानित मूल्य", "item", "वस्तु")):
        return {}

    idx_sched = _col_index(header_cells, "evaluation schedules", "मूल्यांकन अनुसूचियां")
    idx_item  = _col_index(header_cells, "item/category", "item", "वस्तु")
    idx_value = _col_index(header_cells, "estimated value", "अनुमानित मूल्य")
    idx_qty   = _col_index(header_cells, "quantity", "मात्रा")
    if idx_sched is None: idx_sched = 0
    if idx_item  is None: idx_item  = 1
    if idx_value is None: idx_value = 2
    if idx_qty   is None: idx_qty   = 3

    schedules: dict = {}
    running = 0
    for row in rows[1:]:
        cells = [clean(td.get_text()) for td in row.find_all(["td", "th"])]
        if not cells:
            continue
        item_cat = _cell_val(cells, idx_item)
        if not item_cat or item_cat.lower() in ("item/category", "item", ""):
            continue
        sched_label = _cell_val(cells, idx_sched)
        num = to_int(sched_label)
        running += 1
        key = str(num) if num else str(running)
        schedules[key] = {
            "Item/Category":   item_cat,
            "Estimated Value": _cell_val(cells, idx_value),
            "Quantity":        _cell_val(cells, idx_qty),
        }
    return schedules


def parse_evaluation_section(docling: dict, kv: dict, soup: BeautifulSoup = None) -> dict:
    """
    Extract evaluation method (Total-wise, Item-wise, or Group-wise) and parse corresponding schedules.
    
    Args:
        docling (dict): Parsed JSON document dictionary.
        kv (dict): Table key-value map.
        soup (BeautifulSoup, optional): HTML soup for table extraction fallback.
        
    Returns:
        dict: Evaluation dictionary with method and schedules map.
    """
    d      = docling.get("evaluation", {})
    method = docling_first(
        d, "evaluation_method",
        lambda: md_get(kv, "Evaluation Method", "मूल्यांकन पढ़ति", "मूल्यांकन विधि") or "")
    method_lower = method.lower()

    if "total" in method_lower:
        return {"evaluation_method": method, "schedules": {}}

    if "item" in method_lower:
        raw = d.get("schedules", {})
        schedules: dict = {}
        for key, val in raw.items():
            if isinstance(val, dict):
                schedules[str(key)] = {
                    "Item/Category":   val.get("Item/Category", ""),
                    "Estimated Value": val.get("Estimated Value", ""),
                    "Quantity":        val.get("Quantity", ""),
                }
        if not schedules and soup is not None:
            schedules = _parse_item_wise_schedules(soup)
        return {"evaluation_method": method, "schedules": schedules}

    if "group" in method_lower:
        raw = d.get("schedules", {})
        schedules = {}
        if raw:
            for key, val in raw.items():
                if isinstance(val, dict):
                    first_sub = next(iter(val.values()), None)
                    if isinstance(first_sub, dict):
                        new_key = _normalise_group_key(key)
                        items: dict = {}
                        for item_key, item_val in val.items():
                            if isinstance(item_val, dict):
                                items[item_key] = {
                                    "Item/Category": item_val.get(
                                        "Item/Ca tegory", item_val.get("Item/Category", "")),
                                    "Consignee/Reporting Officer": item_val.get(
                                        "Consignee/Repor ting Officer",
                                        item_val.get("Consignee/Reporting Officer", "")),
                                    "Consignee Address": item_val.get("Consignee Address", ""),
                                    "Quantity": item_val.get(
                                        "Qua ntity", item_val.get("Quantity", "")),
                                }
                        schedules[new_key] = items
        if not schedules and soup is not None:
            schedules = _parse_group_wise_schedules(soup)
        return {"evaluation_method": method, "schedules": schedules}

    return {"evaluation_method": method, "schedules": d.get("schedules", {})}


# ---------------------------------------------------------------------------
# Section 4 — Documents
# ---------------------------------------------------------------------------
def parse_documents_section(docling: dict, kv: dict) -> dict:
    """
    Extract required seller documents and visibility flags from parsed data or key-value table.
    
    Args:
        docling (dict): Parsed JSON dictionary.
        kv (dict): Key-value dictionary.
        
    Returns:
        dict: Required documents list, document visibility flag, and attachments.
    """
    d = docling.get("documents", {})

    def _docs_fallback():
        raw = md_get(kv, "Document required from seller",
                      "विक्रेता से मांगे गए", "विकेता से") or ""
        return [clean(x) for x in re.split(r",\s*(?=[A-Z*])", raw) if clean(x)]

    docs_list = docling_first(d, "required_from_seller", _docs_fallback)

    show_raw = docling_first(
        d, "show_uploaded_docs_to_all_bidders",
        lambda: md_get(kv, "Do you want to show documents", "क्या आप निविदाकारों") or "No")
    show_val = "Yes" if "yes" in str(show_raw).lower() else "No"
    return {
        "required_from_seller":              docs_list,
        "show_uploaded_docs_to_all_bidders": show_val,
        "attachments":                       d.get("attachments", []),
    }


# ---------------------------------------------------------------------------
# Section 5 — Consignees
# ---------------------------------------------------------------------------
def _col_idx(hdr_cells: list[str], *kws: str) -> Optional[int]:
    """Helper to locate column index in consignee header list."""
    for i, h in enumerate(hdr_cells):
        if any(k.lower() in h for k in kws):
            return i
    return None


def parse_consignees_section(docling: dict, soup: BeautifulSoup = None) -> list:
    """
    Parse consignees, reporting officers, delivery addresses, quantities, and delivery schedules.
    
    Args:
        docling (dict): Parsed JSON dictionary.
        soup (BeautifulSoup, optional): HTML soup fallback.
        
    Returns:
        list[dict]: List of consignee detail dictionaries.
    """
    raw = docling.get("consignees", [])
    if raw:
        result = []
        for c in raw:
            result.append({
                "consignee_reporting_officer": c.get("consignee_reporting_officer", ""),
                "consignee_address":           c.get("consignee_address", ""),
                "quantity":                    str(c.get("quantity", "")),
                "delivery_days":               str(c.get("delivery_days", "")),
            })
        return result
    if soup is None:
        return []
    seen: set[tuple] = set()
    result = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        hdr = " ".join(clean(td.get_text()) for td in rows[0].find_all(["td", "th"])).lower()
        if "consignee" not in hdr and "reporting" not in hdr and "परेषिती" not in hdr:
            continue
        if "quantity" not in hdr and "मात्रा" not in hdr and "माना" not in hdr:
            continue
        hdr_cells = [clean(td.get_text()).lower() for td in rows[0].find_all(["td", "th"])]
        i_sno  = _col_idx(hdr_cells, "s.no", "क्र.सं")
        i_off  = _col_idx(hdr_cells, "reporting", "consignee reporting", "परेषिती/रिपोर्टिंग")
        i_addr = _col_idx(hdr_cells, "address", "पता")
        i_qty  = _col_idx(hdr_cells, "quantity", "मात्रा", "माना")
        i_del  = _col_idx(hdr_cells, "delivery", "डिलीवरी")
        if i_off is None: i_off  = 1
        if i_addr is None: i_addr = 2
        if i_qty is None:  i_qty  = 3
        if i_del is None:  i_del  = 4
        for row in rows[1:]:
            cells = [clean(td.get_text()) for td in row.find_all(["td", "th"])]
            if len(cells) < 4:
                continue
            if i_sno is not None and i_sno < len(cells):
                if not re.fullmatch(r"\d+", cells[i_sno]):
                    continue
            officer  = cells[i_off]  if i_off  < len(cells) else ""
            address  = cells[i_addr] if i_addr < len(cells) else ""
            quantity = cells[i_qty]  if i_qty  < len(cells) else ""
            delivery = cells[i_del]  if i_del  < len(cells) else ""
            if not officer or any(kw in officer.lower() for kw in
                                  ["officer", "consignee", "reporting", "अधिकारी"]):
                continue
            key = (officer, address, quantity, delivery)
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "consignee_reporting_officer": officer,
                "consignee_address":           address,
                "quantity":                    quantity,
                "delivery_days":               delivery,
            })
    return result


# ---------------------------------------------------------------------------
# Section 6 — Relaxations, Auto-Extension, RA, Bid Type
# ---------------------------------------------------------------------------
def parse_relaxations_auto_extension_ra_bid_type(
        docling: dict, kv: dict) -> tuple[dict, dict, dict, dict]:
    """
    Parse MSE/Startup relaxations, auto extension settings, Reverse Auction (RA) options, and bid type rules.
    
    Args:
        docling (dict): Parsed JSON dictionary.
        kv (dict): Key-value table dictionary.
        
    Returns:
        tuple[dict, dict, dict, dict]: (relaxations, auto_extension, ra, bid_type).
    """
    r = docling.get("relaxations", {})
    relaxations = {
        "mse_relaxation_experience_turnover": yesno(docling_first(
            r, "mse_relaxation_experience_turnover",
            lambda: md_get(kv, "MSE Relaxation", "एमाएसएमई के लिए अनुभव",
                            "एमएसएमई के लिए अनुभव") or "No")),
        "startup_relaxation_experience_turnover": yesno(docling_first(
            r, "startup_relaxation_experience_turnover",
            lambda: md_get(kv, "Startup Relaxation", "स्टार्टअप के लिए अनुभव") or "No")),
    }

    ae = docling.get("auto_extension", {})
    auto_extension = {
        "min_bids_to_disable_extension": docling_first(
            ae, "min_bids_to_disable_extension",
            lambda: to_int(md_get(kv, "Minimum number of bids",
                                   "बिड लगाने की समय सीमा स्वतः") or "")),
        "auto_extend_days": docling_first(
            ae, "auto_extend_days",
            lambda: to_int(md_get(kv, "Number of days for which Bid",
                                   "दिनों की संख्या") or "")),
        "auto_extension_count": docling_first(
            ae, "auto_extension_count",
            lambda: to_int(md_get(kv, "Number of Auto Extension",
                                   "ऑटो एक्सर्टेशन", "ऑटो एक्सटैशन") or "")),
    }

    ra_d  = docling.get("ra", {})
    ra_yn = yesno(docling_first(
        ra_d, "bid_to_ra_enabled",
        lambda: md_get(kv, "Bid to RA enabled", "बिड से रिवर्स नीलामी") or "No"))
    ra = {
        "bid_to_ra_enabled": ra_yn,
        "ra_qualification_rule":
            (docling_first(ra_d, "ra_qualification_rule",
                            lambda: md_get(kv, "RA Qualification Rule", "रिवर्स नीलामी योग्यता")))
            if ra_yn == "Yes" else None,
    }

    bt = docling.get("bid_type", {})
    bid_type = {
        "type_of_bid": docling_first(
            bt, "type_of_bid",
            lambda: md_get(kv, "Type of Bid", "बिड का प्रकार") or ""),
        "technical_clarification_window_days": docling_first(
            bt, "technical_clarification_window_days",
            lambda: to_int(md_get(kv, "Time allowed for Technical Clarification",
                                   "तकनीकी मूल्यांकन के दौरान") or "")),
    }
    return relaxations, auto_extension, ra, bid_type


# ---------------------------------------------------------------------------
# Section 7 — Inspection & Clauses
# ---------------------------------------------------------------------------
def parse_inspection_and_clauses(docling: dict, kv: dict = None) -> tuple[dict, dict]:
    """
    Parse inspection requirements and legal arbitration/mediation clauses.
    
    Args:
        docling (dict): Parsed JSON dictionary.
        kv (dict, optional): Key-value dictionary.
        
    Returns:
        tuple[dict, dict]: (inspection_dict, clauses_dict).
    """
    kv = kv or {}
    ins = docling.get("inspection", {})
    inspection = {
        "inspection_required": yesno(docling_first(
            ins, "inspection_required",
            lambda: md_get(kv, "Inspection Required", "निरीक्षण आवश्यक") or "No")),
        "inspection_agency_type": ins.get("inspection_agency_type"),
    }
    cl = docling.get("clauses", {})
    clauses = {
        "arbitration_clause": yesno(docling_first(
            cl, "arbitration_clause",
            lambda: md_get(kv, "Arbitration Clause", "मध्यस्थता खंड") or "No")),
        "mediation_clause": yesno(docling_first(
            cl, "mediation_clause",
            lambda: md_get(kv, "Mediation Clause", "सुलह खंड") or "No")),
    }
    return inspection, clauses


# ---------------------------------------------------------------------------
# Section 8 — MII & MSE
# ---------------------------------------------------------------------------
def parse_mii_mse_section(docling: dict, kv: dict = None) -> tuple[dict, dict]:
    kv  = kv or {}
    mi  = docling.get("mii", {})
    ms  = docling.get("mse", {})

    def _mii(field, *md_patterns):
        return docling_first(mi, field, lambda: yesno(md_get(kv, *md_patterns) or "") or None)

    def _mii_int(field, *md_patterns):
        return docling_first(mi, field, lambda: to_int(md_get(kv, *md_patterns) or ""))

    def _mse(field, *md_patterns):
        return docling_first(ms, field, lambda: yesno(md_get(kv, *md_patterns) or "") or None)

    def _mse_int(field, *md_patterns):
        return docling_first(ms, field, lambda: to_int(md_get(kv, *md_patterns) or ""))

    mii = {
        "mii_purchase_preference":
            _mii("mii_purchase_preference", "MII Purchase Preference", "एमआईआई खरीद वरीयता"),
        "mii_price_band_percent":
            _mii_int("mii_price_band_percent",
                     "Purchase Preference to MII", "मेक इन इंडिया विक्रेताओं को"),
        "mii_max_quantity_percent":
            _mii_int("mii_max_quantity_percent",
                     "Maximum Percentage of Bid quantity for MII",
                     "मेक इन इंडिया खरीद में प्राथमिकता के लिए बिड"),
        "allow_only_class_1_2_local_suppliers": docling_first(
            mi, "allow_only_class_1_2_local_suppliers",
            lambda: ("Yes" if (raw := md_get(kv, "Allow participation only from Class",
                                              "सार्वजनिक खरीद", "सार्यजनिक खरीद"))
                             and "yes" in raw.lower() else None)),
    }
    mse = {
        "mse_purchase_preference":
            _mse("mse_purchase_preference", "MSE Purchase Preference", "एमएसई खरीद वरीयता"),
        "mse_price_band_percent":
            _mse_int("mse_price_band_percent", "Purchase Preference to MSE", "सूक्ष्म और लघु"),
        "mse_max_quantity_percent":
            _mse_int("mse_max_quantity_percent",
                     "Maximum Percentage of Bid quantity for MSE",
                     "Percentage of Bid quantity/amount for MSE"),
    }
    return mii, mse


# ---------------------------------------------------------------------------
# Section 9 — Financials
# ---------------------------------------------------------------------------
def parse_financials_section(docling: dict, kv: dict = None, md_content: str = "") -> dict:
    kv   = kv or {}
    fin  = docling.get("financials", {})
    emd  = fin.get("emd",  {})
    epbg = fin.get("epbg", {})

    emd_bank = docling_first(
        emd, "advisory_bank", lambda: md_get(kv, "Advisory Bank", "एडवाईजरी बैंक") or "")
    epbg_bank = docling_first(
        epbg, "advisory_bank", lambda: md_get(kv, "Advisory Bank", "एडवाइजरी बैंक") or "")

    def _emd_amount_fallback():
        total = 0
        for k, v in kv.items():
            if "emd amount" in k.lower() or "ईएमडी राशि" in k.lower():
                amt = to_int(v)
                if amt:
                    total += amt
        return total if total else None

    emd_amount = docling_first(emd, "amount_total", _emd_amount_fallback)

    emd_required = docling_first(
        emd, "required", lambda: bool(emd_bank or emd_amount))

    epbg_required = docling_first(epbg, "required", lambda: bool(epbg_bank))
    epbg_pct = docling_first(
        epbg, "percent",
        lambda: to_float(md_get(kv, "ePBG Percentage", "ईपीबीजी प्रतिशत") or ""))
    epbg_dur = docling_first(
        epbg, "duration_months",
        lambda: to_int(md_get(kv, "Duration of ePBG", "ईपीबीजी की आवश्यक अवधि") or ""))

    def _emd_exempt_fallback():
        text = md_get(kv, "EMD EXEMPTION", "emd exemption", "ईएमडी छूट") or ""
        if not text and md_content:
            m = re.search(
                r"EMD EXEMPTION[:\s]*(.*?)(?:\n\n|\(b\)|\(c\)|$)",
                md_content, re.DOTALL | re.IGNORECASE)
            if m:
                text = clean(m.group(1))
        return text

    emd_exempt = docling_first(fin, "emd_exemption_text", _emd_exempt_fallback)

    return {
        "emd": {
            "required":         emd_required,
            "advisory_bank":    emd_bank,
            "amount_total":     emd_amount,
            "schedule_breakup": emd.get("schedule_breakup", []),
        },
        "epbg": {
            "required":        epbg_required,
            "advisory_bank":   epbg_bank,
            "percent":         epbg_pct,
            "duration_months": epbg_dur,
        },
        "emd_exemption_text": emd_exempt,
    }


# ---------------------------------------------------------------------------
# Section 10 — Terms / Buyer ATC
# ---------------------------------------------------------------------------
_ATC_HEADING_RE = re.compile(
    r"buyer added bid specific terms and conditions", re.IGNORECASE)
_DISCLAIMER_LABEL_RE = re.compile(r"disclaimer", re.IGNORECASE)
_DISCLAIMER_BOILERPLATE_RE = re.compile(
    r"(?:the\s+additional\s+)?terms and conditions(?:\s*\(atc\))?\s+"
    r"have been incorporated by the buyer after approval",
    re.IGNORECASE)
_THANK_YOU_RE = re.compile(r"thank you", re.IGNORECASE)


def _trim_boundary_debris(text: str) -> str:
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"(#+\s*)$", "", text)
        text = re.sub(r"([^\s]{1,60}/\s*)$", "", text)
        text = re.sub(r"(-{2,}\s*)$", "", text)
        text = text.rstrip()
    return text.strip()


def parse_terms_buyer_atc(docling: dict, md_content: str = "") -> dict:
    t   = docling.get("terms", {})
    atc = t.get("buyer_atc", {})
    generic    = atc.get("generic", "")
    disclaimer = t.get("disclaimer", "")

    if (not generic or not disclaimer) and md_content:
        atc_m = _ATC_HEADING_RE.search(md_content)
        atc_start = atc_m.start() if atc_m else None

        search_from = atc_start if atc_start is not None else 0
        disc_label_m = _DISCLAIMER_LABEL_RE.search(md_content, search_from)
        disc_boiler_m = None if disc_label_m else \
            _DISCLAIMER_BOILERPLATE_RE.search(md_content, search_from)

        if disc_label_m:
            disc_section_start   = disc_label_m.start()
            disc_content_start   = disc_label_m.end()
        elif disc_boiler_m:
            disc_section_start   = disc_boiler_m.start()
            disc_content_start   = disc_boiler_m.start()
        else:
            disc_section_start = disc_content_start = None

        search_end_from = disc_content_start if disc_content_start is not None \
            else (atc_start if atc_start is not None else 0)
        thank_m = _THANK_YOU_RE.search(md_content, search_end_from)
        section_end = thank_m.start() if thank_m else len(md_content)

        if not generic and atc_start is not None:
            generic_end = disc_section_start if disc_section_start is not None else section_end
            generic = _trim_boundary_debris(clean(md_content[atc_start:generic_end]))

        if not disclaimer and disc_content_start is not None:
            disclaimer = _trim_boundary_debris(clean(md_content[disc_content_start:section_end]))

    return {
        "special_terms_version": t.get("special_terms_version", ""),
        "special_terms_text":    t.get("special_terms_text", ""),
        "buyer_atc": {
            "generic":           generic,
            "items":             atc.get("items", []),
            "hard_requirements": atc.get("hard_requirements", []),
            "info_clauses":      atc.get("info_clauses", []),
        },
        "disclaimer": disclaimer,
    }


# =========================================================
# MAIN PDF PARSING ENTRYPOINT
# =========================================================
def parse_bid_data(md_content: str | dict, product_type: str = "PRODUCT") -> dict:
    """
    Parses Mineru Markdown string into structured PDF JSON schema.
    Supports both raw markdown string and dict returned by Mineru Zero Save Mode (output_dir=None).
    """
    if isinstance(md_content, dict):
        md_content = md_content.get("markdown", "")
    if not isinstance(md_content, str):
        md_content = str(md_content or "")
    if "Custom Bid for Services" in md_content or "Custom BOQ" in md_content:
        process_kind = "CUSTOM"
        base_type = f"CUSTOM_{product_type.upper()}"
    elif "BOQ Title" in md_content or "BOQ Detail Document" in md_content:
        process_kind = "BOQ"
        base_type = "BOQ"
    else:
        process_kind = "CATALOGUE"
        base_type = product_type.upper()

    soup = BeautifulSoup(md_content, "html.parser")
    kv   = md_table_kv(soup)
    docling = {}

    timing, departments                       = parse_pdf_section(docling, kv)
    items                                     = parse_items_section(docling, kv, soup)
    evaluation                                = parse_evaluation_section(docling, kv, soup)
    documents                                 = parse_documents_section(docling, kv)
    consignees                                = parse_consignees_section(docling, soup)
    relaxations, auto_extension, ra, bid_type = parse_relaxations_auto_extension_ra_bid_type(docling, kv)
    inspection, clauses                       = parse_inspection_and_clauses(docling, kv)
    mii, mse                                  = parse_mii_mse_section(docling, kv)
    financials                                = parse_financials_section(docling, kv, md_content)
    terms                                     = parse_terms_buyer_atc(docling, md_content)

    return {
        "process_kind":   process_kind,
        "base_type":      base_type,
        "timing":         timing,
        "departments":    departments,
        "items":          items,
        "evaluation":     evaluation,
        "documents":      documents,
        "consignees":     consignees,
        "relaxations":    relaxations,
        "auto_extension": auto_extension,
        "ra":             ra,
        "bid_type":       bid_type,
        "inspection":     inspection,
        "clauses":        clauses,
        "mii":            mii,
        "mse":            mse,
        "financials":     financials,
        "terms":          terms,
    }


# =========================================================
# HYPERLINK EXTRACTION (PyMuPDF / fitz)
# =========================================================
def extract_pdf_hyperlinks(pdf_path: str, source_tag: str = "bid") -> list[dict]:
    """
    Extract external embedded hyperlinks from a PDF file using PyMuPDF (fitz).
    Deduplicates links by (uri, text, source_tag) and ignores internal page-jump links.
    
    Args:
        pdf_path (str): Path to the PDF file.
        source_tag (str): Origin label for the document ('bid' or 'ra').
        
    Returns:
        list[dict]: List of extracted hyperlink objects.
    """
    if not pdf_path or not os.path.exists(pdf_path):
        return []
    
    extracted_data = []
    seen = set()
    
    try:
        import fitz
        with fitz.open(pdf_path) as doc:
            for page_num in range(len(doc)):
                page = doc[page_num]
                links = page.get_links()
                for link in links:
                    try:
                        # 1. Filter: Only external URI links
                        if link.get("kind") != fitz.LINK_URI:
                            continue
                        uri = link.get("uri", "").strip()
                        if not uri or not uri.lower().startswith(("http://", "https://")):
                            continue
                        
                        # 2. Extract bounding text with correct empty fallback
                        rect = link.get("from")
                        raw_text = page.get_textbox(rect).strip() if rect else ""
                        text = clean_text(raw_text) or "View Document"
                        
                        # 3. Deduplicate identical (uri, text, source_tag) entries
                        key = (uri, text, source_tag)
                        if key in seen:
                            continue
                        seen.add(key)
                        
                        extracted_data.append({
                            "page": page_num + 1,
                            "text": text,
                            "url": uri,
                            "source": source_tag
                        })
                    except Exception as link_err:
                        log.debug(f"Skipping malformed link on page {page_num+1} ({source_tag}): {link_err}")
    except Exception as e:
        log.debug(f"Error extracting PDF hyperlinks from {pdf_path}: {e}")
        
    return extracted_data


# =========================================================
# CARD HTML EXTRACTION (v3 Schema Implementation)
# =========================================================
def get_ra_from_card(card) -> str:
    """
    Extract Reverse Auction (RA) document number (e.g. GEM/2026/R/12345) from Playwright card element.
    
    Args:
        card: Playwright Locator pointing to a bid card DOM node.
        
    Returns:
        str: RA number string or empty string if not found.
    """
    try:
        text = card.inner_text()
        m = re.search(r"GEM/\d{4}/R/\d+", text)
        return m.group() if m else ""
    except Exception as e:
        log.debug(f"RA card scrape: {e}")
    return ""


def get_product_type_from_card(card, bid_type_name: str) -> str:
    """
    Extract product category type (Product, Service, Works, Goods) from card text or default map.
    
    Args:
        card: Playwright card locator.
        bid_type_name (str): Bid type string label.
        
    Returns:
        str: Normalized product type title string.
    """
    from config.settings import PRODUCT_TYPE_MAP
    try:
        text = card.inner_text()
        m = re.search(r"(?:Type\s*[:\-]\s*)(Product|Service|Works|Goods)", text, re.IGNORECASE)
        if m:
            return m.group(1).title()
        for kw in ["Service", "Product", "Works", "Goods"]:
            if re.search(rf"\b{kw}\b", text, re.IGNORECASE):
                return kw.title()
    except Exception as e:
        log.debug(f"Product type card: {e}")
    return PRODUCT_TYPE_MAP.get(bid_type_name, bid_type_name)


def get_dates_from_card(card) -> tuple[str, str]:
    """
    Extract Start Date and End Date from Playwright HTML card and convert times to 24-hour format.
    
    Args:
        card: Playwright card element.
        
    Returns:
        tuple[str, str]: (start_datetime, end_datetime) strings formatted as 'DD-MM-YYYY HH:MM:SS'.
    """
    start_date, end_date = "", ""
    try:
        text = card.inner_text()
        start_m = re.search(r"Start\s+Date\s*[:\-]?\s*(\d{2}-\d{2}-\d{4})\s+(\d{1,2}:\d{2})\s*(AM|PM)?", text, re.IGNORECASE)
        if start_m:
            date_part = start_m.group(1)
            time_part = _to_24h(start_m.group(2), start_m.group(3) or "")
            start_date = f"{date_part} {time_part}"

        end_m = re.search(r"End\s+Date\s*[:\-]?\s*(\d{2}-\d{2}-\d{4})\s+(\d{1,2}:\d{2})\s*(AM|PM)?", text, re.IGNORECASE)
        if end_m:
            date_part = end_m.group(1)
            time_part = _to_24h(end_m.group(2), end_m.group(3) or "")
            end_date = f"{date_part} {time_part}"
    except Exception as e:
        log.debug(f"Card date scrape error: {e}")
    return start_date, end_date


def _to_24h(time_str: str, ampm: str) -> str:
    """Helper to convert 12-hour time string with AM/PM indicator to HH:MM:SS 24-hour format."""
    try:
        parts = time_str.strip().split(":")
        hour = int(parts[0])
        mins = int(parts[1]) if len(parts) > 1 else 0
        ampm = ampm.strip().upper()
        if ampm == "PM" and hour != 12: hour += 12
        elif ampm == "AM" and hour == 12: hour = 0
        return f"{hour:02d}:{mins:02d}:00"
    except Exception:
        return f"{time_str}:00"


_POPOVER_ATTRS = ("data-content", "data-original-title", "title")


def _read_popover_attr(node) -> str:
    """Read HTML data attributes from Bootstrap popover element node."""
    for attr in _POPOVER_ATTRS:
        try:
            val = node.get_attribute(attr)
            if val and val.strip(): return _strip_html(val)
        except Exception:
            continue
    return ""


def get_full_item_name_from_card(card) -> str:
    """
    Extract complete item name string by checking popover data attributes and text fallback.
    
    Args:
        card: Playwright Locator of card DOM node.
        
    Returns:
        str: Full item title/category description string.
    """
    try:
        items_node = card.locator("xpath=.//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'items:')]").first
        if items_node and items_node.count() > 0:
            txt = _read_popover_attr(items_node)
            if txt:
                txt = re.sub(r"^\s*items?\s*:\s*", "", txt, flags=re.IGNORECASE)
                return txt

        for attr in _POPOVER_ATTRS:
            cand = card.locator(f"[{attr}]").first
            if cand and cand.count() > 0:
                val = cand.get_attribute(attr) or ""
                if val and len(val.strip()) > 15:
                    return _strip_html(val)
    except Exception as e:
        log.debug(f"Popover lookup failed: {e}")

    try:
        text = card.inner_text()
        m = re.search(r"Items?\s*:\s*(.+?)(?:\n|Quantity\s*:)", text, re.IGNORECASE | re.DOTALL)
        if m: return clean_text(m.group(1)).rstrip(".")
    except Exception:
        pass
    return ""


def get_quantity_from_card(card) -> int:
    """
    Extract total item quantity integer value listed on card.
    
    Args:
        card: Playwright Locator of card node.
        
    Returns:
        int: Quantity parsed from card.
    """
    try:
        text = card.inner_text()
        m = re.search(r"Quantity\s*[:\-]?\s*([\d][\d,]*)", text, re.IGNORECASE)
        if m: return int(m.group(1).replace(",", "").strip())
    except Exception as e:
        log.debug(f"Quantity card scrape: {e}")
    return 0


def get_departments_from_card(card) -> list:
    """
    Extract department name, address, and pincode list from card text.
    
    Args:
        card: Playwright Locator of card node.
        
    Returns:
        list[dict]: Department details dictionary list.
    """
    try:
        text = card.inner_text()
        m = re.search(r"Department\s+Name(?:\s+And\s+Address)?\s*[:\-]?\s*\n?([^\n]+(?:\n[^\n]+)*?(?=\nStart Date|\Z))", text, re.IGNORECASE)
        if m:
            lines = [l.strip() for l in m.group(1).split('\n') if l.strip()]
            if lines:
                name = lines[0]
                address = ", ".join(lines[1:]) if len(lines) > 1 else ""
                pincode = re.search(r'\b\d{6}\b', address)
                return [{
                    "name": name,
                    "address": address,
                    "city": "",   
                    "state": "",  
                    "pincode": pincode.group() if pincode else ""
                }]
    except Exception as e:
        log.debug(f"Department card scrape: {e}")
    return []


def get_bid_no_from_card(card) -> str:
    """
    Extract Bid Number (e.g. GEM/2026/B/1234567) from card inner text.
    
    Args:
        card: Playwright Locator of card node.
        
    Returns:
        str: Matched Bid number or empty string.
    """
    try:
        text = card.inner_text()
        m = re.search(r"GEM/\d{4}/B/\d+", text)
        return m.group() if m else ""
    except Exception:
        return ""


def get_card_details(card, bid_type_name: str) -> dict:
    """
    Assemble complete structured card details dictionary from Playwright HTML card element.
    
    Args:
        card: Playwright card node locator.
        bid_type_name (str): Label of selected bid type category.
        
    Returns:
        dict: Standardized card object containing 'bid' metadata and 'card' parameters.
    """
    start_date, end_date = get_dates_from_card(card)
    return {
        "bid": {
            "bid_no": get_bid_no_from_card(card),
            "ra_no": get_ra_from_card(card),
            "bid_type": bid_type_name,
            "product_type": get_product_type_from_card(card, bid_type_name),
            "base_type": "",    
            "process_kind": ""  
        },
        "card": {
            "items": [
                {
                    "name": get_full_item_name_from_card(card),
                    "quantity": get_quantity_from_card(card)
                }
            ],
            "departments": get_departments_from_card(card),
            "start_datetime": start_date,
            "end_datetime": end_date,
            "bid_pdf_url": "", 
            "ra_pdf_url": ""   
        }
    }