"""
core/normalizer.py — Data Normalization & Validation Engine for GeM Bids.

Provides standard normalization for currencies, dates (ISO 8601), quantities,
EMD/ePBG financial instruments, and Make in India / MSE preferences.
Performs data integrity and schema validation, reporting errors and warnings.
"""

from __future__ import annotations
import re
from datetime import datetime, timezone
from typing import Optional, Any
from utils.logger import get_logger

log = get_logger("normalizer")


# ---------------------------------------------------------------------------
# CURRENCY & FINANCIAL HELPERS
# ---------------------------------------------------------------------------
def parse_currency_to_number(val: Any) -> Optional[float]:
    """
    Parse Indian currency expressions into a clean float value in INR.

    Supported formats:
        - "1885000", "18,85,000", 1885000
        - "18.85 Lakh", "18.85 Lakhs", "18.85 Lacs" -> 1885000.0
        - "1.5 Crore", "1.50 Crores", "1.5 Cr"      -> 15000000.0
        - "50 Thousand", "50k"                       -> 50000.0
        - "₹ 1,50,000 /-"                            -> 150000.0
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)

    s = str(val).strip()
    if not s:
        return None

    # Remove currency symbols (₹, Rs., INR) and trailing slashes
    s = re.sub(r"(?:₹|Rs\.?|INR|\/-)", " ", s, flags=re.IGNORECASE).strip()

    # Check Crore
    m_cr = re.search(r"([\d\.]+)\s*(?:crore|cr|crores)\b", s, re.IGNORECASE)
    if m_cr:
        try:
            return round(float(m_cr.group(1)) * 10_000_000.0, 2)
        except ValueError:
            pass

    # Check Lakh
    m_lakh = re.search(r"([\d\.]+)\s*(?:lakh|lacs|lac|lakhs)\b", s, re.IGNORECASE)
    if m_lakh:
        try:
            return round(float(m_lakh.group(1)) * 100_000.0, 2)
        except ValueError:
            pass

    # Check Thousand
    m_k = re.search(r"([\d\.]+)\s*(?:thousand|k)\b", s, re.IGNORECASE)
    if m_k:
        try:
            return round(float(m_k.group(1)) * 1_000.0, 2)
        except ValueError:
            pass

    # Plain digits with optional commas
    clean_digits = re.sub(r"[^\d\.]", "", s)
    if clean_digits:
        try:
            return round(float(clean_digits), 2)
        except ValueError:
            pass

    return None


def format_inr_currency(amount: Optional[float]) -> str:
    """
    Format a numeric INR float into a human-friendly Indian currency string.
    Examples:
        - 15000000.0 -> "₹1.50 Crore"
        - 1885000.0  -> "₹18.85 Lakh"
        - 50000.0    -> "₹50,000"
    """
    if amount is None or amount <= 0:
        return "₹0"

    if amount >= 10_000_000:
        cr = amount / 10_000_000.0
        return f"₹{cr:.2f} Crore".rstrip("0").rstrip(".") if cr.is_integer() else f"₹{cr:.2f} Crore"
    elif amount >= 100_000:
        lakh = amount / 100_000.0
        return f"₹{lakh:.2f} Lakh"
    else:
        # Standard Indian number formatting
        s = f"{int(amount)}"
        if len(s) <= 3:
            return f"₹{s}"
        last_three = s[-3:]
        rest = s[:-3]
        parts = []
        while len(rest) > 2:
            parts.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.insert(0, rest)
        formatted = ",".join(parts) + "," + last_three
        return f"₹{formatted}"


# ---------------------------------------------------------------------------
# DATE & TIME HELPERS
# ---------------------------------------------------------------------------
def parse_datetime_to_iso(dt_str: Optional[str]) -> Optional[str]:
    """
    Parse varied GeM date/time strings into standardized ISO 8601 strings.
    Converts Indian Standard Time (IST, UTC+05:30) strings.

    Formats recognized:
        - "24-07-2026 11:00:00" (24-hour DD-MM-YYYY HH:MM:SS)
        - "24-07-2026 11:00:00 AM" / "PM"
        - "24-07-2026 11:00 AM" / "PM"
        - "24-07-2026 11:00"
        - "24-07-2026"
        - "2026-07-24T11:00:00"
    """
    if not dt_str:
        return None

    cleaned = str(dt_str).strip()
    if not cleaned:
        return None

    # Common patterns
    formats = [
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %I:%M:%S %p",
        "%d-%m-%Y %I:%M %p",
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]

    # Normalize multiple spaces
    cleaned = re.sub(r"\s+", " ", cleaned)

    for fmt in formats:
        try:
            dt = datetime.strptime(cleaned, fmt)
            # Represent in ISO 8601 with IST offset
            return dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
        except ValueError:
            continue

    # Try fallback for ISO input
    try:
        dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
    except Exception:
        pass

    return None


def calculate_date_metrics(start_iso: Optional[str], end_iso: Optional[str]) -> tuple[Optional[float], Optional[float], bool]:
    """
    Calculate bid duration in days, days remaining, and expired status.

    Returns:
        (duration_days, days_remaining, is_expired)
    """
    duration_days = None
    days_remaining = None
    is_expired = False

    dt_start = None
    dt_end = None

    if start_iso:
        try:
            dt_start = datetime.fromisoformat(start_iso)
        except Exception:
            pass

    if end_iso:
        try:
            dt_end = datetime.fromisoformat(end_iso)
        except Exception:
            pass

    now = datetime.now(timezone.utc)

    if dt_start and dt_end:
        duration_days = round((dt_end - dt_start).total_seconds() / 86400.0, 2)

    if dt_end:
        # Compare in timezone-aware fashion
        if dt_end.tzinfo is None:
            dt_end = dt_end.replace(tzinfo=timezone.utc)
        diff_sec = (dt_end - now).total_seconds()
        days_remaining = round(diff_sec / 86400.0, 2)
        is_expired = diff_sec < 0

    return duration_days, days_remaining, is_expired


# ---------------------------------------------------------------------------
# MAIN NORMALIZATION FUNCTION
# ---------------------------------------------------------------------------
def normalize_bid_data(
    card_data: Optional[dict] = None,
    parsed_pdf_data: Optional[dict] = None,
    pdf_text: str = ""
) -> dict:
    """
    Produce a complete, standardized 'normalized' dictionary from card and PDF inputs.

    Args:
        card_data (dict, optional): Scraped card dictionary containing 'bid' and 'card'.
        parsed_pdf_data (dict, optional): Extracted PDF details (financials, departments, items, etc.).
        pdf_text (str): Full PDF text for fallback regex queries.

    Returns:
        dict: Standardized normalized schema.
    """
    card_data = card_data or {}
    parsed_pdf_data = parsed_pdf_data or {}
    card = card_data.get("card", {})
    bid_meta = card_data.get("bid", {})

    # 1. Dates
    start_raw = card.get("start_datetime") or parsed_pdf_data.get("timing", {}).get("bid_start_datetime")
    end_raw = card.get("end_datetime") or parsed_pdf_data.get("timing", {}).get("bid_end_datetime")

    start_iso = parse_datetime_to_iso(start_raw)
    end_iso = parse_datetime_to_iso(end_raw)
    duration_days, days_remaining, is_expired = calculate_date_metrics(start_iso, end_iso)

    # 2. Financials & Estimated Value
    fin = parsed_pdf_data.get("financials", {})
    raw_est_val = fin.get("estimated_value")

    # If missing from financials, check evaluation schedules or text
    if not raw_est_val:
        eval_data = parsed_pdf_data.get("evaluation", {})
        schedules = eval_data.get("schedules", {})
        if schedules and isinstance(schedules, dict):
            sched_total = 0.0
            found_sched_val = False
            for s in schedules.values():
                if isinstance(s, dict):
                    val_str = s.get("Estimated Value") or s.get("estimated_value")
                    num = parse_currency_to_number(val_str)
                    if num:
                        sched_total += num
                        found_sched_val = True
            if found_sched_val and sched_total > 0:
                raw_est_val = sched_total

    # Text fallback for estimated value
    if not raw_est_val and pdf_text:
        m = re.search(
            r"(?:Estimated\s+Bid\s+Value|अनुमानित\s+बिड\s+मूल्य)[^\d<|\n]*([\d,]+(?:\.\d+)?)",
            pdf_text,
            re.IGNORECASE
        )
        if m:
            raw_est_val = m.group(1)

    est_val_inr = parse_currency_to_number(raw_est_val)
    est_val_formatted = format_inr_currency(est_val_inr)
    high_value_tender = bool(est_val_inr and est_val_inr >= 5_000_000.0)

    # 3. EMD & ePBG
    emd_info = fin.get("emd", {})
    emd_amount = parse_currency_to_number(emd_info.get("amount_total"))
    emd_required = bool(emd_info.get("required") or (emd_amount and emd_amount > 0))

    epbg_info = fin.get("epbg", {})
    epbg_required = bool(epbg_info.get("required"))
    epbg_percent = epbg_info.get("percent")
    try:
        epbg_percent = float(epbg_percent) if epbg_percent is not None else None
    except (ValueError, TypeError):
        epbg_percent = None

    # 4. Multi-Item Catalog & Quantities
    card_items = card.get("items", [])
    pdf_items = parsed_pdf_data.get("items", {})

    items_list = []
    total_qty = 0

    # Build from PDF item schedules if present
    if pdf_items and isinstance(pdf_items, dict):
        for k, v in pdf_items.items():
            if re.match(r"^item \d+$", k, re.IGNORECASE) and isinstance(v, dict):
                cat = v.get("item_category", "").strip()
                q = v.get("quantity")
                try:
                    q_num = int(q) if q is not None else 0
                except (ValueError, TypeError):
                    q_num = 0
                if cat:
                    items_list.append({"name": cat, "quantity": q_num})
                    total_qty += q_num

    # Fallback to card items if PDF item blocks were not individual items
    if not items_list and card_items:
        for it in card_items:
            name = it.get("name", "").strip()
            q = it.get("quantity")
            try:
                q_num = int(q) if q is not None else 0
            except (ValueError, TypeError):
                q_num = 0
            if name:
                # If name contains multiple comma-separated items, unpack them
                if " , " in name:
                    sub_names = [s.strip() for s in name.split(" , ") if s.strip()]
                    for sn in sub_names:
                        items_list.append({"name": sn, "quantity": q_num if len(sub_names) == 1 else 0})
                elif "," in name and len(name.split(",")) > 1 and not re.search(r"sa\d+|is\d+", name, re.IGNORECASE):
                    # Check if standard comma-separated item list
                    sub_names = [s.strip() for s in name.split(",") if s.strip()]
                    for sn in sub_names:
                        items_list.append({"name": sn, "quantity": q_num if len(sub_names) == 1 else 0})
                else:
                    items_list.append({"name": name, "quantity": q_num})
                total_qty += q_num

    # If total_qty is 0, fall back to card quantity
    if total_qty == 0 and card_items:
        try:
            total_qty = int(card_items[0].get("quantity") or 0)
        except (ValueError, TypeError):
            total_qty = 0

    # 5. Policy & Preferences
    relaxations = parsed_pdf_data.get("relaxations", {})
    mse_relax = str(relaxations.get("mse_relaxation_experience_turnover", "")).strip().lower().startswith("yes")
    startup_relax = str(relaxations.get("startup_relaxation_experience_turnover", "")).strip().lower().startswith("yes")

    mii_pref = parsed_pdf_data.get("mii", {})
    mse_pref = parsed_pdf_data.get("mse_preference", {})

    return {
        "financials": {
            "estimated_value_inr": est_val_inr,
            "estimated_value_formatted": est_val_formatted,
            "high_value_tender": high_value_tender,
            "emd": {
                "required": emd_required,
                "amount_inr": emd_amount,
                "amount_formatted": format_inr_currency(emd_amount),
                "advisory_bank": emd_info.get("advisory_bank", ""),
            },
            "epbg": {
                "required": epbg_required,
                "percentage": epbg_percent,
                "advisory_bank": epbg_info.get("advisory_bank", ""),
                "duration_months": epbg_info.get("duration_months"),
            },
        },
        "dates": {
            "start_date_iso": start_iso,
            "end_date_iso": end_iso,
            "bid_duration_days": duration_days,
            "days_remaining": days_remaining,
            "is_expired": is_expired,
        },
        "items": {
            "total_items_count": len(items_list) if items_list else 1,
            "total_quantity": total_qty,
            "items_breakdown": items_list,
        },
        "preferences": {
            "mse_relaxation": mse_relax,
            "startup_relaxation": startup_relax,
            "mii_preference": bool(mii_pref.get("purchase_preference") == "Yes"),
            "mse_preference": bool(mse_pref.get("purchase_preference") == "Yes"),
        },
    }


# ---------------------------------------------------------------------------
# MAIN VALIDATION FUNCTION
# ---------------------------------------------------------------------------
def validate_bid_data(
    bid_no: str = "",
    card_data: Optional[dict] = None,
    parsed_pdf_data: Optional[dict] = None,
    normalized: Optional[dict] = None,
    pdf_path: Optional[str] = None
) -> dict:
    """
    Validate bid structure and completeness, reporting errors and warnings.

    Returns:
        dict: Standardized validation object:
            {
                "is_valid": bool,
                "error_count": int,
                "warning_count": int,
                "issues": [{"field": str, "severity": "error"|"warning", "message": str}]
            }
    """
    card_data = card_data or {}
    parsed_pdf_data = parsed_pdf_data or {}
    normalized = normalized or {}
    issues = []

    # 1. Bid Number validation
    if not bid_no:
        issues.append({
            "field": "bid_no",
            "severity": "error",
            "message": "Missing Bid Number."
        })
    elif not re.match(r"^GEM[/_]\d{4}[/_][A-Z][/_]\d+", bid_no, re.IGNORECASE):
        issues.append({
            "field": "bid_no",
            "severity": "warning",
            "message": f"Bid number '{bid_no}' does not follow standard GEM/YYYY/X/NNNNNN pattern."
        })

    # 2. Date checks
    dates = normalized.get("dates", {})
    if not dates.get("start_date_iso"):
        issues.append({
            "field": "start_datetime",
            "severity": "warning",
            "message": "Could not parse valid start date."
        })

    if not dates.get("end_date_iso"):
        issues.append({
            "field": "end_datetime",
            "severity": "error",
            "message": "Missing or unparsable bid end date."
        })

    if dates.get("bid_duration_days") is not None and dates["bid_duration_days"] < 0:
        issues.append({
            "field": "dates",
            "severity": "error",
            "message": "End date precedes start date."
        })

    if dates.get("is_expired"):
        issues.append({
            "field": "dates",
            "severity": "warning",
            "message": f"Bid expired {abs(dates.get('days_remaining', 0))} days ago."
        })

    # 3. Items checks
    items_info = normalized.get("items", {})
    if items_info.get("total_items_count", 0) == 0:
        issues.append({
            "field": "items",
            "severity": "warning",
            "message": "No item names extracted from bid card or PDF."
        })

    if items_info.get("total_quantity", 0) <= 0:
        issues.append({
            "field": "quantity",
            "severity": "warning",
            "message": "Extracted total quantity is 0 or negative."
        })

    # 4. Department checks
    card_depts = card_data.get("card", {}).get("departments", [])
    has_dept = False
    if card_depts and isinstance(card_depts, list):
        first_d = card_depts[0]
        if any(first_d.get(k) for k in ("name", "department_name", "ministry_state_name", "organisation_name")):
            has_dept = True

    if not has_dept:
        issues.append({
            "field": "department",
            "severity": "warning",
            "message": "Department hierarchy details are empty."
        })

    # 5. Financials checks
    fin = normalized.get("financials", {})
    emd = fin.get("emd", {})
    if emd.get("required") and not emd.get("amount_inr"):
        issues.append({
            "field": "emd",
            "severity": "warning",
            "message": "EMD is required but total amount is unspecified or zero."
        })

    # 6. PDF file check
    if pdf_path:
        import os
        if not os.path.exists(pdf_path):
            issues.append({
                "field": "pdf_path",
                "severity": "error",
                "message": f"Target PDF file does not exist on disk: {pdf_path}"
            })
        elif os.path.getsize(pdf_path) == 0:
            issues.append({
                "field": "pdf_path",
                "severity": "error",
                "message": "Target PDF file is empty (0 bytes)."
            })

    error_count = sum(1 for x in issues if x["severity"] == "error")
    warning_count = sum(1 for x in issues if x["severity"] == "warning")

    return {
        "is_valid": error_count == 0,
        "error_count": error_count,
        "warning_count": warning_count,
        "issues": issues,
    }
