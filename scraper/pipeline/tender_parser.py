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
# UNIFIED SCHEMA
# Both formats map to this same dict structure so the
# rest of the pipeline (database, RAG) doesn't care which
# format the API returned.
# =========================================================
UNIFIED_FIELDS = [
    "tender_id",          # internal API id
    "tender_no",          # official tender number
    "tender_reference_id",# GEM bid no or state portal ref
    "status",             # OPEN | AOC | CLOSED
    "platform",           # GEM | eProcure | etc.
    "source_name",        # Gem | Maharashtra Tenders Portal | etc.
    "source_url",         # procurement_source / ref_url
    "tender_type",        # Open Tender | Limited | etc.
    "procurement_type",   # Services | Goods | Works
    "bidding_type",       # Tender | Goods | Services
    "competition_type",   # NCB | ICB | etc.
    "category",           # Paper And Printing Services
    "sub_category",       # Printing Related Service
    "product_name",       # Printing Work
    "sector",             # Public Administrative Department
    "authority",          # Issuing organization
    "ownership",          # Government Departments | PSU | etc.
    "city",
    "state",
    "country",
    "address",
    "address_pin",
    "contact_person",
    "contact_email",
    "contact_phone",
    "tender_summary",     # short description
    "work_desc",          # full description
    "search_text",        # categories/keywords
    "tender_value",       # estimated value INR
    "doc_cost",           # document cost INR
    "earnest_amount",     # EMD INR
    "pub_date",           # published date
    "enter_date",         # entered in system
    "due_date",           # submission deadline
    "open_date",          # bid opening date
    "is_corrigendum",
    "document_urls",      # list of PDF download URLs
    # ── Result-only fields (AOC) ──────────────────────────
    "contract_date",      # award date
    "contract_value",     # actual awarded amount INR
    "completion_date",    # contract duration
    "winner_name",        # winning bidder name
    "winner_bid",         # winning bid amount
    "all_bidders",        # list of all bidders with amounts
]


def _empty_record() -> dict:
    return {f: "" for f in UNIFIED_FIELDS}


# =========================================================
# FORMAT 1 PARSER — active_tenders
# =========================================================
def parse_active_tender(raw: dict) -> dict:
    rec = _empty_record()
    rec["tender_id"]           = raw.get("tender_id", "")
    rec["tender_no"]           = raw.get("tender_no", "")
    rec["tender_reference_id"] = raw.get("tender_reference_id", "")
    rec["status"]              = raw.get("tender_status", "OPEN")
    rec["platform"]            = ", ".join(raw.get("platforms", []))
    rec["source_name"]         = raw.get("procurement_source_name", "")
    rec["source_url"]          = raw.get("procurement_source", "")
    rec["tender_type"]         = raw.get("tender_type", "")
    rec["procurement_type"]    = raw.get("procurement_type", "")
    rec["bidding_type"]        = raw.get("bidding_type", "")
    rec["competition_type"]    = raw.get("competition_type", "")
    rec["category"]            = raw.get("category", "")
    rec["sub_category"]        = raw.get("sub_category", "")
    rec["product_name"]        = raw.get("product_name", "")
    rec["sector"]              = raw.get("sector", "")
    rec["authority"]           = raw.get("authority", "")
    rec["ownership"]           = raw.get("ownership", "")
    rec["city"]                = raw.get("city", "")
    rec["state"]               = raw.get("state", "")
    rec["country"]             = raw.get("country", "India")
    rec["address"]             = raw.get("address", "")
    rec["address_pin"]         = raw.get("address_pin", "")
    rec["contact_person"]      = raw.get("contact_person", "")
    rec["contact_email"]       = raw.get("contact_email", "")
    rec["contact_phone"]       = raw.get("contact_phone", "")
    rec["tender_summary"]      = raw.get("tender_summary", "")
    rec["work_desc"]           = raw.get("work_desc", "")
    rec["search_text"]         = raw.get("search_text", "")
    rec["is_corrigendum"]      = str(raw.get("is_corrigendum", False))

    # Money — MongoDB $numberDecimal format
    rec["tender_value"]   = _decimal(raw.get("tender_value", 0))
    rec["doc_cost"]       = _decimal(raw.get("doc_cost", 0))
    rec["earnest_amount"] = _decimal(raw.get("earnest_amount", 0))

    # Dates — MongoDB $numberLong format
    rec["pub_date"]   = _ts_to_str(raw.get("pub_date"))
    rec["enter_date"] = _ts_to_str(raw.get("enter_date"))
    rec["due_date"]   = _ts_to_str(raw.get("due_date"))
    rec["open_date"]  = _ts_to_str(raw.get("open_date"))

    # Documents — has tender_download_path
    rec["document_urls"] = _doc_urls(raw.get("s3_document_path", []))

    return rec


# =========================================================
# FORMAT 2 PARSER — tender_results
# =========================================================
def parse_tender_result(raw: dict) -> dict:
    # Unwrap OpenSearch envelope
    src = raw.get("_source", raw)

    rec = _empty_record()
    rec["tender_id"]           = src.get("tender_result_id", "")
    rec["tender_no"]           = src.get("tender_no", "")
    rec["tender_reference_id"] = src.get("tender_reference_id", "")
    rec["status"]              = src.get("tender_status", "AOC")
    rec["platform"]            = ", ".join(src.get("platforms", []))
    rec["source_name"]         = src.get("procurement_source_name", "")
    rec["source_url"]          = src.get("ref_url", "")
    rec["tender_type"]         = ""  # not in result format
    rec["procurement_type"]    = ""  # not in result format
    rec["bidding_type"]        = ""  # not in result format
    rec["competition_type"]    = ""  # not in result format
    rec["category"]            = src.get("category", "")
    rec["sub_category"]        = src.get("sub_category", "")
    rec["product_name"]        = src.get("product_name", src.get("product", ""))
    rec["sector"]              = src.get("sector", "")
    rec["authority"]           = src.get("authority", "")
    rec["ownership"]           = src.get("ownership", "")
    rec["city"]                = src.get("city", "")
    rec["state"]               = src.get("state", "")
    rec["country"]             = "India"
    rec["address"]             = ""  # not in result format
    rec["address_pin"]         = ""
    rec["contact_person"]      = ""
    rec["contact_email"]       = ""
    rec["contact_phone"]       = ""
    rec["tender_summary"]      = ""  # not in result format
    rec["work_desc"]           = src.get("work_desc", "")
    rec["search_text"]         = src.get("search_text", "")
    rec["is_corrigendum"]      = "False"

    # Money — plain float (no MongoDB wrapper)
    rec["tender_value"]   = _decimal(src.get("tender_value", 0))
    rec["doc_cost"]       = ""
    rec["earnest_amount"] = ""

    # Dates — plain integer timestamps (no MongoDB wrapper)
    rec["pub_date"]   = _ts_to_str(src.get("pub_date"))
    rec["enter_date"] = _ts_to_str(src.get("enter_date"))
    rec["due_date"]   = _ts_to_str(src.get("due_date"))
    rec["open_date"]  = _ts_to_str(src.get("open_date"))

    # Result-specific fields
    rec["contract_date"]    = _ts_to_str(src.get("contract_date"))
    rec["contract_value"]   = str(src.get("contract_value", ""))
    rec["completion_date"]  = src.get("completion_date", "")

    # Winner and all bidders
    bidders = src.get("bidder_list", [])
    w = _winner(bidders)
    rec["winner_name"] = w.get("bidder_name", "")
    rec["winner_bid"]  = str(w.get("bid_amount", ""))
    rec["all_bidders"] = json.dumps([
        {
            "name":   b.get("bidder_name", ""),
            "amount": b.get("bid_amount", 0),
            "rank":   b.get("rank", 0),
            "status": "Winner" if b.get("aoc_status") == 1
                      else "Rejected" if b.get("aoc_status") == 2
                      else "Disqualified",
        }
        for b in sorted(bidders, key=lambda x: x.get("rank", 99))
    ])

    # Documents — NO download URL in result format
    rec["document_urls"] = []

    return rec


# =========================================================
# AUTO-DETECT & PARSE
# Detects which format the API returned and parses it.
# =========================================================
def parse_api_response(raw_json: str | list | dict) -> list[dict]:
    """
    Pass raw JSON string, parsed list, or parsed dict.
    Returns list of unified records regardless of format.
    """
    if isinstance(raw_json, str):
        # tender_result format: multiple root-level objects
        # (not a valid JSON array — fix by wrapping)
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
            # Format 2: OpenSearch envelope
            records.append(parse_tender_result(item))
        elif "tender_id" in item:
            # Format 1: active_tenders
            records.append(parse_active_tender(item))
        elif "tender_result_id" in item:
            # Format 2 already unwrapped
            records.append(parse_tender_result({"_source": item}))
        else:
            log.warning(f"Unknown tender format — skipping: {list(item.keys())[:5]}")

    log.info(f"Parsed {len(records)} tenders from API response")
    return records

