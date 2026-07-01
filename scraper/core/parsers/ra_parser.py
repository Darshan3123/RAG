import re
from scraper.core.parser import clean_text

def parse_ra_intelligence(pdf_text: str) -> dict:
    """
    Parse RA-specific information from the RA document PDF text.
    """
    ra_intel = {
        "ra_start_datetime": None,
        "ra_end_datetime": None,
        "auto_extension": {
            "enabled": False,
            "window_minutes": 15
        },
        "mse_relaxation_experience_turnover": False,
        "startup_relaxation_experience_turnover": False,
    }

    if not pdf_text:
        return ra_intel

    # 1. RA Start Date/Time
    ra_start_m = re.search(
        r"RA\s+Start\s+Date\s*/\s*Time\s*[:\-]?\s*(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2})",
        pdf_text, re.IGNORECASE,
    )
    if ra_start_m:
        ra_intel["ra_start_datetime"] = ra_start_m.group(1)

    # 2. RA End Date/Time
    ra_end_m = re.search(
        r"RA\s+End\s+Date\s*/\s*Time\s*[:\-]?\s*(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2})",
        pdf_text, re.IGNORECASE,
    )
    if ra_end_m:
        ra_intel["ra_end_datetime"] = ra_end_m.group(1)

    # 3. Auto Extension
    if "auto extension" in pdf_text.lower() or "auto-extension" in pdf_text.lower():
        ra_intel["auto_extension"]["enabled"] = True

    ae_window_m = re.search(
        r"(?:auto\s*extension|extend).*?(\d+)\s*min",
        pdf_text, re.IGNORECASE,
    )
    if ae_window_m:
        ra_intel["auto_extension"]["window_minutes"] = int(ae_window_m.group(1))

    # 4. Exemptions
    mse_relax_m = re.search(
        r"MSE\s+(?:Relaxation|Exemption)\s+for\s+Years\s+Of\s+Experience"
        r"(?:\s+and\s+Turnover)?\s*[:\-]?\s*(Yes|No)",
        pdf_text, re.IGNORECASE,
    )
    if mse_relax_m:
        ra_intel["mse_relaxation_experience_turnover"] = mse_relax_m.group(1).strip().lower() == "yes"

    startup_m = re.search(
        r"Startup\s+(?:Relaxation|Exemption)\s+for\s+Years\s+Of\s+Experience"
        r"(?:\s+and\s+Turnover)?\s*[:\-]?\s*(Yes|No)",
        pdf_text, re.IGNORECASE,
    )
    if startup_m:
        ra_intel["startup_relaxation_experience_turnover"] = startup_m.group(1).strip().lower() == "yes"

    return ra_intel
