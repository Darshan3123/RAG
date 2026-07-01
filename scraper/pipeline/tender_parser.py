# =========================================================
# pipeline/tender_parser.py
# Parses BOTH API response formats into a unified schema:
#
# FORMAT 1 — active_tenders  (status = OPEN)
#   - Root is a JSON array of tender objects
#   - Timestamps wrapped in {"$numberLong": "..."}
#   - Money wrapped in {"$numberDecimal": "..."}
#   - Has tender_download_path on each s3_document_path item
#   - NO bidder_list, NO contract_value
#
# FORMAT 2 — tender_results  (status = AOC / completed)
#   - Root is multiple JSON objects (NOT an array)
#   - Each wrapped in {_index, _id, _score, _source, highlight}
#   - Actual data lives inside _source
#   - Timestamps are plain integers
#   - Money is plain float
#   - Has bidder_list with winner info
#   - Has contract_value, contract_date, completion_date
#   - s3_document_path has NO tender_download_path
# =========================================================
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from shared.utils.logger import get_logger

log = get_logger("tender_parser")


# =========================================================
# HELPERS
# =========================================================
def _ts_to_str(value) -> str:
    """Convert millisecond timestamp (any format) → DD-MM-YYYY HH:MM:SS"""
    if not value:
        return ""
    try:
        if isinstance(value, dict):
            ms = int(value.get("$numberLong", 0))
        else:
            ms = int(value)
        if ms <= 0:
            return ""
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        return dt.strftime("%d-%m-%Y %H:%M:%S")
    except Exception:
        return str(value)


def _decimal(value) -> str:
    """Extract float from MongoDB $numberDecimal or plain number."""
    if not value and value != 0:
        return ""
    try:
        if isinstance(value, dict):
            v = float(value.get("$numberDecimal", 0))
        else:
            v = float(value)
        return str(v) if v > 0 else ""
    except Exception:
        return str(value)


def _winner(bidder_list: list) -> dict:
    """Return the winning bidder (aoc_status == 1, rank == 1)."""
    for b in bidder_list:
        if b.get("aoc_status") == 1 and b.get("rank") == 1:
            return b
    # fallback: lowest rank with aoc_status == 1
    winners = [b for b in bidder_list if b.get("aoc_status") == 1]
    return min(winners, key=lambda x: x.get("rank", 99)) if winners else {}


def _doc_urls(s3_list: list) -> list[str]:
    """Extract all download URLs from s3_document_path."""
    urls = []
    for item in s3_list:
        url = item.get("tender_download_path", "")
        if url:
            urls.append(url)
    return urls


# =========================================================
# UNIFIED NESTED SCHEMA
# Both API formats map to the same base structure so the
# rest of the pipeline doesn't care which format it returned.
# (API data lacks full PDF intelligence, so many fields stay empty)
# =========================================================

def _empty_record() -> dict:
    return {
        "bid": {
            "bid_no": "",
            "ra_no": "",
            "bid_type": "",
            "product_type": "",
            "base_type": "",
            "process_kind": ""
        },
        "card": {
            "items": [],
            "departments": [],
            "start_datetime": "",
            "end_datetime": "",
            "bid_pdf_url": "",
            "ra_pdf_url": ""
        },
        "pdf": {
            "timing": {
                "bid_end_datetime": "",
                "bid_opening_datetime": "",
                "bid_offer_validity_days": None
            },
            "departments": [],
            "items": [],
            "documents": {
                "required_from_seller": [],
                "show_uploaded_docs_to_all_bidders": False,
                "attachments": []
            },
            "consignees": [],
            "relaxations": {
                "mse_relaxation_experience_turnover": False,
                "startup_relaxation_experience_turnover": False
            },
            "auto_extension": {
                "min_bids_to_disable_extension": None,
                "auto_extend_days": None,
                "auto_extension_count": None
            },
            "ra": {
                "bid_to_ra_enabled": False,
                "ra_qualification_rule": "",
                "ra_start_datetime": "",
                "ra_end_datetime": "",
                "auto_extension": {
                    "enabled": False,
                    "window_minutes": 15
                },
                "mse_relaxation_experience_turnover": False,
                "startup_relaxation_experience_turnover": False
            },
            "bid_type": {
                "type_of_bid": "",
                "technical_clarification_window_days": None
            },
            "inspection": {
                "inspection_required": False,
                "inspection_agency_type": ""
            },
            "evaluation": {
                "evaluation_method": "",
                "schedules": []
            },
            "clauses": {
                "arbitration_clause": False,
                "mediation_clause": False
            },
            "mii": {
                "mii_purchase_preference": False,
                "mii_price_band_percent": None,
                "mii_max_quantity_percent": None,
                "allow_only_class_1_2_local_suppliers": False
            },
            "mse": {
                "mse_purchase_preference": False,
                "mse_price_band_percent": None,
                "mse_max_quantity_percent": None
            },
            "financials": {
                "emd": {
                    "required": False,
                    "advisory_bank": None,
                    "amount_total": 0,
                    "schedule_breakup": []
                },
                "epbg": {
                    "required": False,
                    "advisory_bank": None,
                    "percent": None,
                    "duration_months": None
                },
                "emd_exemption_text": ""
            },
            "terms": {
                "special_terms_version": "",
                "special_terms_text": "",
                "buyer_atc": {
                    "generic": "",
                    "items": [],
                    "hard_requirements": [],
                    "info_clauses": []
                },
                "disclaimer": ""
            }
        },
        "normalized": {
            "status": "OPEN",
            "tender_id": "",
            "source": "",
            "tender_value": "",
            "doc_cost": "",
            "platform": "",
            "pub_date": ""
        },
        "validation": {
            "issues": []
        },
        "full_pdf_text": ""
    }


def _try_float(val) -> float | None:
    try:
        if isinstance(val, dict):
            return float(val.get("$numberDecimal", 0))
        return float(val) if val else None
    except Exception:
        return None


def _get_api_datetime(val) -> str:
    """Format an API date cleanly to DD-MM-YYYY HH:MM:SS"""
    return _ts_to_str(val)


# =========================================================
# FORMAT 1 PARSER — active_tenders
# =========================================================
def parse_active_tender(raw: dict) -> dict:
    rec = _empty_record()
    
    bid_no = raw.get("tender_no", "")
    rec["bid"]["bid_no"] = bid_no
    rec["bid"]["bid_type"] = raw.get("tender_type", "")
    rec["bid"]["product_type"] = raw.get("procurement_type", "")
    pt_lower = rec["bid"]["product_type"].lower()
    rec["bid"]["base_type"] = "PRODUCT" if "good" in pt_lower or "product" in pt_lower else "SERVICE" if "service" in pt_lower else "CUSTOM"
    rec["bid"]["process_kind"] = "CATALOGUE"
    
    # Card level
    rec["card"]["start_datetime"] = _get_api_datetime(raw.get("pub_date"))
    rec["card"]["end_datetime"] = _get_api_datetime(raw.get("due_date"))
    
    # Single item from summary
    if raw.get("product_name"):
        rec["card"]["items"].append({
            "name": raw.get("product_name", ""),
            "quantity": None
        })
        rec["pdf"]["items"].append({
            "schedule_no": 1,
            "item_category": raw.get("category", "") + " - " + raw.get("sub_category", ""),
            "quantity": None
        })
        
    # Department
    dept = {
        "ministry_state_name": raw.get("state", ""),
        "department_name": raw.get("authority", ""),
        "organisation_name": raw.get("ownership", ""),
        "office_name": raw.get("city", "")
    }
    rec["pdf"]["departments"].append(dept)
    
    # Consignee fallback
    rec["pdf"]["consignees"].append({
        "consignee_name": raw.get("contact_person", ""),
        "address_raw": raw.get("address", ""),
        "pincode": raw.get("address_pin", ""),
        "city": raw.get("city", ""),
        "state": raw.get("state", ""),
        "quantity": None,
        "delivery_days": None
    })
    
    # Timing
    rec["pdf"]["timing"]["bid_end_datetime"] = rec["card"]["end_datetime"]
    rec["pdf"]["timing"]["bid_opening_datetime"] = _get_api_datetime(raw.get("open_date"))
    
    # Financials
    emd_amt = _try_float(raw.get("earnest_amount", 0))
    if emd_amt and emd_amt > 0:
        rec["pdf"]["financials"]["emd"]["required"] = True
        rec["pdf"]["financials"]["emd"]["amount_total"] = emd_amt

    # Normalized fields (for RAG/UI)
    rec["normalized"]["status"] = raw.get("tender_status", "OPEN")
    rec["normalized"]["tender_id"] = raw.get("tender_id", "")
    rec["normalized"]["source"] = raw.get("procurement_source_name", "")
    rec["normalized"]["tender_value"] = _try_float(raw.get("tender_value", 0))
    rec["normalized"]["doc_cost"] = _try_float(raw.get("doc_cost", 0))
    rec["normalized"]["platform"] = ", ".join(raw.get("platforms", []))
    rec["normalized"]["pub_date"] = rec["card"]["start_datetime"]

    # Documents
    doc_urls = _doc_urls(raw.get("s3_document_path", []))
    if doc_urls:
        rec["card"]["bid_pdf_url"] = doc_urls[0]
        
    return rec


# =========================================================
# FORMAT 2 PARSER — tender_results
# =========================================================
def parse_tender_result(raw: dict) -> dict:
    src = raw.get("_source", raw)
    rec = _empty_record()
    
    rec["bid"]["bid_no"] = src.get("tender_no", "")
    rec["bid"]["product_type"] = "Unknown"
    rec["bid"]["base_type"] = "PRODUCT"
    
    rec["card"]["start_datetime"] = _get_api_datetime(src.get("pub_date"))
    rec["card"]["end_datetime"] = _get_api_datetime(src.get("due_date"))
    
    if src.get("product_name") or src.get("product"):
        rec["card"]["items"].append({
            "name": src.get("product_name", src.get("product", "")),
            "quantity": None
        })
        
    # Department
    dept = {
        "ministry_state_name": src.get("state", ""),
        "department_name": src.get("authority", ""),
        "organisation_name": src.get("ownership", ""),
        "office_name": src.get("city", "")
    }
    rec["pdf"]["departments"].append(dept)
    
    # Timing
    rec["pdf"]["timing"]["bid_end_datetime"] = rec["card"]["end_datetime"]
    rec["pdf"]["timing"]["bid_opening_datetime"] = _get_api_datetime(src.get("open_date"))
    
    # Financials
    emd_amt = _try_float(src.get("earnest_amount", 0))
    if emd_amt and emd_amt > 0:
        rec["pdf"]["financials"]["emd"]["required"] = True
        rec["pdf"]["financials"]["emd"]["amount_total"] = emd_amt

    # Normalized fields
    rec["normalized"]["status"] = src.get("tender_status", "AOC")
    rec["normalized"]["tender_id"] = src.get("tender_result_id", "")
    rec["normalized"]["source"] = src.get("procurement_source_name", "")
    rec["normalized"]["tender_value"] = _try_float(src.get("tender_value", 0))
    rec["normalized"]["contract_value"] = _try_float(src.get("contract_value", 0))
    rec["normalized"]["contract_date"] = _get_api_datetime(src.get("contract_date"))
    rec["normalized"]["pub_date"] = rec["card"]["start_datetime"]

    # Winner details
    bidders = src.get("bidder_list", [])
    w = _winner(bidders)
    rec["normalized"]["winner_name"] = w.get("bidder_name", "")
    rec["normalized"]["winner_bid"] = _try_float(w.get("bid_amount", 0))
    
    return rec


# =========================================================
# AUTO-DETECT & PARSE
# =========================================================
def parse_api_response(raw_json: str | list | dict) -> list[dict]:
    if isinstance(raw_json, str):
        text = raw_json.strip()
        if not text.startswith("["):
            text = "[" + text + "]"
        data = json.loads(text)
    elif isinstance(raw_json, dict):
        data = [raw_json]
    else:
        data = raw_json

    records = []
    for item in data:
        if "_source" in item:
            records.append(parse_tender_result(item))
        elif "tender_id" in item:
            records.append(parse_active_tender(item))
        elif "tender_result_id" in item:
            records.append(parse_tender_result({"_source": item}))
        else:
            log.warning(f"Unknown tender format — skipping: {list(item.keys())[:5]}")

    log.info(f"Parsed {len(records)} tenders from API response")
    return records

