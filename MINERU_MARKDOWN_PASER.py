"""
GEM Bid Parser
"""
from __future__ import annotations
import json
import re
import argparse
from pathlib import Path
from typing import Optional
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Directory layout
# ---------------------------------------------------------------------------
BASE_DIR      = Path(__file__).resolve().parent.parent
MD_DIR        = BASE_DIR / "PDF_MARKDOWNS"
DOCLING_DIR   = BASE_DIR / "JSON_REFERENCE"
OUTPUT_DIR    = BASE_DIR / "PARSER" / "OUTPUT"

# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------
_ABSENT = object()


def docling_first(d: dict, key: str, fallback_fn):
    val = d.get(key, _ABSENT)
    return val if val is not _ABSENT else fallback_fn()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def clean(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def to_int(value) -> Optional[int]:
    try:
        digits = re.sub(r"[^\d]", "", str(value))
        return int(digits) if digits else None
    except (ValueError, TypeError):
        return None


def to_float(value) -> Optional[float]:
    try:
        m = re.search(r"[\d.]+", str(value))
        return float(m.group()) if m else None
    except (ValueError, TypeError):
        return None


def yesno(value) -> Optional[str]:
    v = clean(value).lower()
    if not v or v == "none":
        return None
    if v.startswith("yes"):
        return "Yes"
    if v.startswith("no"):
        return "No"
    return None


# ---------------------------------------------------------------------------
# Markdown table helpers
# ---------------------------------------------------------------------------
def md_table_kv(soup: BeautifulSoup) -> dict[str, str]:
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
    for i, h in enumerate(header_cells):
        hl = h.lower()
        if any(kw.lower() in hl for kw in keywords):
            return i
    return None


def _normalise_group_key(raw_key: str) -> str:
    raw_key = str(raw_key).strip()
    if re.fullmatch(r"\d+", raw_key):
        return f"Package {int(raw_key)}"
    m = re.fullmatch(r"group\s+g0*(\d+)", raw_key, re.IGNORECASE)
    if m:
        return f"Package {int(m.group(1))}"
    return raw_key


def _cell_at(item_cells: list[tuple[str, int, int]], idx_in_full_row: int) -> str:
    adj = idx_in_full_row - 1
    return item_cells[adj][0] if 0 <= adj < len(item_cells) else ""


def _parse_group_wise_schedules(soup: BeautifulSoup) -> dict:
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
    return cells[idx] if 0 <= idx < len(cells) else ""


def _parse_item_wise_schedules(soup: BeautifulSoup) -> dict:
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
    for i, h in enumerate(hdr_cells):
        if any(k.lower() in h for k in kws):
            return i
    return None


def parse_consignees_section(docling: dict, soup: BeautifulSoup = None) -> list:
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


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def parse_bid(md_path: Path, docling_path: Optional[Path]) -> dict:
    md_content = md_path.read_text(encoding="utf-8")
    soup       = BeautifulSoup(md_content, "html.parser")
    kv         = md_table_kv(soup)

    if docling_path is not None:
        with docling_path.open(encoding="utf-8") as f:
            docling_root = json.load(f)
        docling = docling_root.get("pdf", docling_root)
    else:
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
        "pdf": {
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
    }


# ---------------------------------------------------------------------------
# Bid discovery + runner
# ---------------------------------------------------------------------------
def find_bid_pairs(bid_id: Optional[str] = None) -> list[tuple[Path, Optional[Path]]]:
    pairs: list[tuple[Path, Optional[Path]]] = []
    folders = [MD_DIR / bid_id] if bid_id else \
              sorted(p for p in MD_DIR.iterdir() if p.is_dir())
    for folder in folders:
        md_files = list(folder.glob("*.md"))
        if not md_files:
            print(f"  [SKIP] No .md file in {folder.name}")
            continue
        docling_file = DOCLING_DIR / f"{folder.name}_DOCLING_EXTRACTED.json"
        if not docling_file.exists():
            print(f"  [WARN] No Docling JSON for {folder.name} — markdown-only mode")
            docling_file = None
        pairs.append((md_files[0], docling_file))
    if not pairs:
        print(
            f"  [WARN] No valid bid pairs found.\n"
            f"         MD_DIR      = {MD_DIR}\n"
            f"         DOCLING_DIR = {DOCLING_DIR}\n"
            f"         Expected structure:\n"
            f"           MD_DIR/<BID_ID>/<BID_ID>.md\n"
            f"           DOCLING_DIR/<BID_ID>_DOCLING_EXTRACTED.json"
        )
    return pairs


def run(bid_id: Optional[str] = None) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pairs = find_bid_pairs(bid_id)
    if not pairs:
        print("No bid pairs found.")
        return
    failed: list[str] = []
    for md_path, docling_path in pairs:
        bid_name = md_path.stem
        print(f"  [PARSING] {bid_name} ...")
        try:
            result   = parse_bid(md_path, docling_path)
            out_path = OUTPUT_DIR / f"{bid_name}_PARSED.json"
            out_path.write_text(
                json.dumps(result, indent=4, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"  [OK]      → {out_path}")
        except Exception as exc:
            print(f"  [ERROR]   {bid_name}: {exc}")
            failed.append(bid_name)
    if failed:
        print(f"\n  {len(failed)} bid(s) failed: {', '.join(failed)}")
    else:
        print(f"\n  All {len(pairs)} bid(s) parsed successfully.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="GEM Bid Parser — Docling JSON primary, Markdown fallback"
    )
    ap.add_argument("bid_id", nargs="?",
                    help="Bid folder name to parse; omit to parse all bids")
    args = ap.parse_args()
    run(args.bid_id)