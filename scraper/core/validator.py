# =========================================================
# scraper/core/validator.py
# Post-processing corrections applied to a parsed 'bid' dict
# BEFORE it is passed to assemble_tender_record().
#
# Keep parser.py for pure extraction; put heuristic fixes here
# so they can be extended without touching the main parser.
# =========================================================
import re
from shared.utils.logger import get_logger

log = get_logger("validator")

# Markers that indicate a 6-digit number belongs to bank/EMD text,
# not a postal PIN code.
_BANK_MARKERS = (
    "A/c No", "Account No", "IFSC", "Bank Name",
    "EMD Amount", "NEFT", "RTGS", "Account Number",
)


# ----------------------------------------------------------
# Individual fixers
# ----------------------------------------------------------

def _fix_emd_amount(bid: dict, issues: list[str]) -> None:
    """
    If EMD is still empty after parsing, do a second-pass search
    directly on the raw PDF text. Catches "ईएमडि ... EMD Amount 17500"
    patterns that the main parser may have missed.
    """
    if bid.get("earnest_amount"):
        return
    text = bid.get("full_pdf_text", "") or ""
    if not text:
        return
    m = re.search(
        r"(?:EMD\s*Amount|ईएमड[^\n]{0,15}Amount|Earnest\s+Money\s+Deposit)[^\d]{0,30}(\d[\d,]*)",
        text, re.IGNORECASE | re.DOTALL,
    )
    if m:
        bid["earnest_amount"] = m.group(1).replace(",", "")
        issues.append("auto_emd_from_pdf_text")
        log.debug(f"  [validator] EMD fixed: {bid['earnest_amount']}")


def _fix_bad_address(bid: dict, issues: list[str]) -> None:
    """
    If the address or address_pin looks like it came from a bank/IFSC line,
    clear both fields so they remain empty rather than wrong.
    """
    addr = bid.get("address") or ""
    if addr and any(marker in addr for marker in _BANK_MARKERS):
        log.debug(f"  [validator] Clearing bad address: {addr[:60]}")
        bid["address"]     = ""
        bid["address_pin"] = ""
        issues.append("cleared_bank_address")


def _fix_category_tail(bid: dict, issues: list[str]) -> None:
    """
    If 'category' or 'search_text' still contains MSE/Startup relaxation
    boilerplate (parser missed it), truncate to before the first known tail kw.
    """
    from scraper.core.parser import _trim_item_tail  # re-use the same list
    for field in ("category", "search_text", "full_item_name"):
        val = bid.get(field) or ""
        if not val:
            continue
        trimmed = _trim_item_tail(val)
        if trimmed != val:
            bid[field] = trimmed
            issues.append(f"trimmed_tail_{field}")
            log.debug(f"  [validator] Trimmed tail in {field}: {trimmed[:60]}")


# ----------------------------------------------------------
# Public entry point
# ----------------------------------------------------------

def post_process_bid(bid: dict) -> tuple[dict, list[str]]:
    """
    Apply all heuristic corrections to *bid* in-place.
    Returns (bid, issues) where issues is a list of string tags
    describing what was auto-corrected (stored as 'parse_issues').

    Call this AFTER merging parsed/extended fields but BEFORE
    assemble_tender_record().
    """
    issues: list[str] = []

    _fix_emd_amount(bid, issues)
    _fix_bad_address(bid, issues)
    _fix_category_tail(bid, issues)

    if issues:
        log.info(f"  [validator] Applied fixes: {issues}")

    return bid, issues
