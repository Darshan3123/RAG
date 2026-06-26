import re

# Import shared extraction logic
from scraper.core.parser import _extract_item_category, _trim_item_tail, clean_text

def _parse_int(text: str) -> int | None:
    """Extract first integer from a string."""
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def _parse_float(text: str) -> float | None:
    """Extract first decimal/integer from a string."""
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    return float(m.group()) if m else None


def parse_product_intelligence(pdf_text: str) -> dict:
    """
    Deep-parse full_pdf_text and return a structured dict with
    6 sub-sections. All fields default to None / [] so callers
    can safely check truthiness without KeyErrors.

    Returns:
    {
        "timeline":     { bid_opening_datetime, bid_validity_days,
                          clarification_window_days },
        "eligibility":  { min_turnover_lakhs, mse_relaxed_turnover_lakhs,
                          startup_exempt, required_docs },
        "ra_rules":     { ra_enabled, elimination_rule,
                          auto_extend_days, auto_extend_max,
                          min_bids_to_disable_extension, bid_type },
        "financials":   { emd_amount, advisory_bank,
                          epbg_percent, epbg_duration_months },
        "consignee_items": [
            { item_name, consignee_location, pincode, quantity, delivery_days }
        ],
        "policy":       { mii_margin_percent, mii_max_quantity_percent,
                          mse_margin_percent, mse_max_quantity_percent }
    }
    """

    # ── 1. TIMELINE ────────────────────────────────────────────────────────────
    timeline: dict = {
        "bid_opening_datetime":      None,
        "bid_validity_days":         None,
        "clarification_window_days": None,
    }

    # Bid Opening Date / Time
    bo_m = re.search(
        r"Bid\s+Opening\s+Date[^\d]{0,20}(\d{2}-\d{2}-\d{4})\s+(\d{2}:\d{2}:\d{2})",
        pdf_text, re.IGNORECASE,
    )
    if bo_m:
        timeline["bid_opening_datetime"] = f"{bo_m.group(1)} {bo_m.group(2)}"

    # Bid Offer Validity (days)
    bov_m = re.search(
        r"Bid\s+(?:Offer\s+)?Validity\s*(?:\([^)]{0,40}\))?\s*[:\-]?\s*(\d+)\s*\(?(?:Days?|दिन)",
        pdf_text, re.IGNORECASE,
    )
    if bov_m:
        timeline["bid_validity_days"] = int(bov_m.group(1))

    # Time for Technical Clarifications (days)
    tc_m = re.search(
        r"Time\s+allowed\s+for\s+Technical\s+Clarifications?[^\d]{0,60}(\d+)\s*Days?",
        pdf_text, re.IGNORECASE,
    ) or re.search(
        r"(?:Clarification\s+(?:Period|Window|Days?))\s*[:\-]?\s*(\d+)\s*\(?(?:Days?|दिन)?",
        pdf_text, re.IGNORECASE,
    )
    if tc_m:
        timeline["clarification_window_days"] = int(tc_m.group(1))

    # ── 2. ELIGIBILITY ─────────────────────────────────────────────────────────
    eligibility: dict = {
        "min_turnover_lakhs":         None,
        "mse_relaxed_turnover_lakhs": None,
        "startup_exempt":             None,
        "required_docs":              [],
    }

    # Minimum Average Annual Turnover
    # PDF layout (multi-line):
    #   "Minimum Average Annual Turnover of the\nbidder (For 3 Years)\n20 Lakh (s)"
    # Strategy: find the label line, then scan forward up to 5 lines for "NN Lakh"
    maat_m = None
    label_pos = re.search(
        r"Minimum\s+Average\s+Annual\s+Turnover",
        pdf_text, re.IGNORECASE,
    )
    if label_pos:
        # Grab the next ~300 chars after the label and search within them
        window = pdf_text[label_pos.end(): label_pos.end() + 300]
        maat_m = re.search(r"(\d[\d,\.]*)\s*Lakh", window, re.IGNORECASE)
    if maat_m:
        raw = re.sub(r"[,\s]", "", maat_m.group(1))
        try:
            eligibility["min_turnover_lakhs"] = float(raw)
        except ValueError:
            pass

    # MSE Turnover Relaxation Value
    mse_to_m = re.search(
        r"MSE\s+(?:Turnover\s+)?Relaxation\s*(?:Value|Amount)?\s*[:\-]?\s*"
        r"([\d,\.]+)\s*(?:\(in\s+lakhs?\)|\(?Lakh|\(?INR)?",
        pdf_text, re.IGNORECASE,
    )
    if mse_to_m:
        raw = re.sub(r"[,\s]", "", mse_to_m.group(1))
        try:
            eligibility["mse_relaxed_turnover_lakhs"] = float(raw)
        except ValueError:
            pass

    # Startup Relaxation (Yes / No)
    startup_m = re.search(
        r"Startup\s+Relaxation\s+for\s+Years\s+of\s+Experience\s+and\s+Turnover\s*[:\-]?\s*(Yes|No)",
        pdf_text, re.IGNORECASE,
    )
    if startup_m:
        eligibility["startup_exempt"] = startup_m.group(1).strip().lower() == "yes"

    # Required seller documents — look for known short labels anywhere in the PDF.
    # GeM PDFs mention these labels both in tables and inline prose.
    _KNOWN_DOCS: list[tuple[str, str]] = [
        (r"Experience\s+Criteria",                  "Experience Criteria"),
        (r"Bidder\s+Turnover",                      "Bidder Turnover"),
        (r"Certificate\s+\(Requested\s+in\s+ATC\)", "Certificate (Requested in ATC)"),
        (r"MSE\s+Certificate",                      "MSE Certificate"),
        (r"MSME\s+(?:Registration|Certificate)",    "MSME Registration"),
        (r"Startup\s+(?:Certificate|Registration)", "Startup Certificate"),
        (r"OEM\s+(?:Certificate|Authorization)",    "OEM Certificate"),
        (r"ISO\s+\d{4,5}(?::\d{4})?",              None),   # capture full label
        (r"CA\s+Certificate|Chartered\s+Accountant\s+Certificate",
                                                    "CA Certificate"),
        (r"Affidavit",                              "Affidavit"),
    ]
    seen: set = set()
    for pattern, label in _KNOWN_DOCS:
        m = re.search(pattern, pdf_text[:25000], re.IGNORECASE)
        if m:
            doc_label = label if label else clean_text(m.group())
            if doc_label not in seen:
                seen.add(doc_label)
                eligibility["required_docs"].append(doc_label)

    # ── 3. RA / BIDDING RULES ──────────────────────────────────────────────────
    ra_rules: dict = {
        "ra_enabled":                    False,
        "elimination_rule":              None,
        "auto_extend_days":              None,
        "auto_extend_max":               None,
        "min_bids_to_disable_extension": None,
        "bid_type":                      None,
    }

    # RA enabled?
    if re.search(r"Reverse\s+Auction|RA\s+(?:is\s+)?(?:enabled|applicable|conducted|to\s+be\s+conducted)",
                 pdf_text, re.IGNORECASE):
        ra_rules["ra_enabled"] = True

    # Elimination rule
    elim_m = re.search(
        r"(?:RA\s+)?Qualification\s+Rule\s*[:\-]?\s*([^\n]{5,120})",
        pdf_text, re.IGNORECASE,
    )
    if elim_m:
        ra_rules["elimination_rule"] = clean_text(elim_m.group(1))

    # Auto-extension days
    ae_days_m = re.search(
        r"(?:Number\s+of\s+[Dd]ays?\s+for\s+auto[-\s]?extension|"
        r"Auto[-\s]?[Ee]xtension\s+[Pp]eriod)\s*[:\-]?\s*(\d+)",
        pdf_text, re.IGNORECASE,
    )
    if ae_days_m:
        ra_rules["auto_extend_days"] = int(ae_days_m.group(1))

    # Max auto-extension count
    ae_max_m = re.search(
        r"(?:Max(?:imum)?\s+Auto[-\s]?[Ee]xtension\s+[Cc]ount|"
        r"Max(?:imum)?\s+[Nn]umber\s+of\s+Auto[-\s]?[Ee]xtension)\s*[:\-]?\s*(\d+)",
        pdf_text, re.IGNORECASE,
    )
    if ae_max_m:
        ra_rules["auto_extend_max"] = int(ae_max_m.group(1))

    # Minimum bids to disable auto-extension
    min_bids_m = re.search(
        r"Minimum\s+(?:number\s+of\s+bids?\s+)?(?:required\s+)?to\s+disable\s+"
        r"(?:automatic\s+)?bid\s+extension\s*[:\-]?\s*(\d+)",
        pdf_text, re.IGNORECASE,
    )
    if min_bids_m:
        ra_rules["min_bids_to_disable_extension"] = int(min_bids_m.group(1))

    # Bid type (Two Packet / Single Packet)
    bid_type_m = re.search(
        r"(?:Bid\s+Type|Type\s+of\s+Bid)\s*[:\-]?\s*([^\n]{3,80})",
        pdf_text, re.IGNORECASE,
    )
    if bid_type_m:
        ra_rules["bid_type"] = clean_text(bid_type_m.group(1))

    # ── 4. FINANCIALS ─────────────────────────────────────────────────────────
    financials: dict = {
        "emd_amount":          None,
        "advisory_bank":       None,
        "epbg_percent":        None,
        "epbg_duration_months": None,
    }

    # EMD amount (numeric)
    emd_m = re.search(
        r"(?:EMD\s*Amount|Earnest\s+Money\s+Deposit)\s*[:\-]?\s*([\d,]+)",
        pdf_text, re.IGNORECASE,
    )
    if emd_m:
        raw = re.sub(r",", "", emd_m.group(1))
        try:
            financials["emd_amount"] = float(raw)
        except ValueError:
            pass

    # Advisory Bank
    bank_m = re.search(
        r"Advisory\s+Bank\s*[:\-]?\s*([A-Za-z][A-Za-z\s&]{2,60}?)(?:\n|,|\.|$)",
        pdf_text, re.IGNORECASE,
    )
    if bank_m:
        financials["advisory_bank"] = clean_text(bank_m.group(1))

    # ePBG Percentage
    epbg_pct_m = re.search(
        r"ePBG\s+Percentage\s*[:\-]?\s*([\d\.]+)\s*%?",
        pdf_text, re.IGNORECASE,
    )
    if epbg_pct_m:
        try:
            financials["epbg_percent"] = float(epbg_pct_m.group(1))
        except ValueError:
            pass

    # ePBG Validity Duration (months)
    epbg_dur_m = re.search(
        r"ePBG\s+(?:Validity\s+)?Duration\s*[:\-]?\s*(\d+)\s*(?:Months?|मही?ने?)?",
        pdf_text, re.IGNORECASE,
    )
    if epbg_dur_m:
        financials["epbg_duration_months"] = int(epbg_dur_m.group(1))

    # ── 5. CONSIGNEE / ITEMISED DELIVERY SCHEDULE ─────────────────────────────
    # PDF structure for multi-item bids:
    #   <ITEM NAME LINE(S)>          ← product heading, e.g. "Brass Bib Cock 15mm"
    #   (local content / tech spec lines...)
    #   Advisory-Please refer attached BOQ...   ← optional advisory
    #   Consignees/Reporting Officer and Quantity  ← main table header
    #   S.No. | Consignee Reporting/Officer | ... ← column header row
    #   1     | <person name>               | <pin,addr> | <qty> | <days>
    #
    # Strategy:
    #   1. Find all "Consignees/Reporting Officer and Quantity" headers
    #      (the main ones — skip advisory lines and bare "Consignee\n" column headers).
    #   2. For each, look backwards for the item name (last English-only non-boilerplate
    #      line before the header).
    #   3. Parse the table rows that follow the header (up to the next item block).
    consignee_items: list[dict] = []

    _BANK_MARKERS = (
        "IFSC", "Account", "A/c", "NEFT", "RTGS", "Bank Name",
        "EMD Amount", "EMD", "Slab", "Advisory Bank", "ePBG",
        "Discount", "in favour", "Beneficiary",
        "Location Address", "zipcode", "zip code",
    )

    # Only match the substantive header lines, not advisory text or bare column headers.
    # A real table header contains "Consignees" + "Reporting Officer".
    # The pattern must work for both:
    #   - Raw PDF text: header ends with \n
    #   - Stored collapsed text (full_pdf_text): newlines replaced with spaces
    real_headers = list(re.finditer(
        r"Consignees?/Reporting\s+Officer[^\n]{0,80}(?:\n|(?=\s+(?:J|L|S|O|G)\.?\s*स|and\s+Quantity))",
        pdf_text, re.IGNORECASE,
    ))
    # Fallback: collapsed text where header has no newline — match by position of "and Quantity"
    if not real_headers:
        real_headers = list(re.finditer(
            r"Consignees?/Reporting\s+Officer\s+and\s+Quantity",
            pdf_text, re.IGNORECASE,
        ))

    # Lines / keywords to skip when reverse-scanning for item name.
    # These are checked with re.search (anywhere in the line).
    _ITEM_NAME_SKIP = re.compile(
        r"(Technical\s+Spec|Specification\s+Doc|BOQ\s+Det|Advisory|"
        r"View\s+File|Buyer\s+Spec|\bDownload\b|Minimum\s+\d+%|"
        r"Local\s+Content|Class\s+[12]\s+Local|\bS\.?\s*No\.?\b|"
        r"Consignee|Reporting\s+Officer|\bS\.\s*N\b|\brespectively\b|"
        r"required\s+for\s+qualifying|as\s+per\s+the\s+tech|"
        r"Content\s+required|Local\s+Supplier|qualifying\s+as|"
        r"price\s+(band|within)|If\s+L[-\s]?[1-9]|"
        r"Warranty|Duration\s+\(Post|Maintenance\s+Duration|"
        r"Comprehensive\s+Maintenance|AMC/CMC|supersede|catalog|"
        r"specf?ication|defined\s+by\s+Buyer|Optional\b|"
        r"Document/[&\s]|/Optional|^\d+\s*/\s*\d+$)",     # page number "6 / 14"
        re.IGNORECASE,
    )

    # Trim trailing "As Per Technical Specification..." from item names
    _ITEM_NAME_TRAIL = re.compile(
        r"\s*(,?\s*as\s+per\s+the\s+tech.*|,?\s*as\s+per\s+tech.*)$",
        re.IGNORECASE,
    )

    # Item name must look like a real product heading:
    # – contains at least one word ≥ 4 chars
    # – not just a generic word like "Year" or "Download"
    _GENERIC_WORDS = re.compile(
        r"^(Year|Years|Month|Months|Day|Days|Yes|No|Set|Sets|Unit|Units|"
        r"Download|View|File|Doc|Document|Period|Duration|Warranty|Certificate)$",
        re.IGNORECASE,
    )

    def _looks_like_item_name(s: str) -> bool:
        words = s.split()
        if len(words) < 1:
            return False
        # At least one word must be ≥ 4 chars and not purely numeric
        real_words = [w for w in words if len(re.sub(r'[^A-Za-z]', '', w)) >= 4]
        if not real_words:
            return False
        # Don't accept single generic words
        if len(words) == 1 and _GENERIC_WORDS.match(words[0]):
            return False
        # Reject "8 Year", "2 Year(s)", "3 Days" etc. (number + unit combos)
        if len(words) <= 2 and re.match(r'^\d+', words[0]) and _GENERIC_WORDS.match(re.sub(r'\W', '', words[-1])):
            return False
        # Reject lines that are pure number lists like "512, 1024, 2048 Or higher"
        # but NOT product names like "300 TB STORAGE" or "Brass Bib Cock 15mm"
        if re.match(r'^\d[\d,\s]+\d\s*$', s):
            return False
        # Reject prose fragments that look like policy text
        if len(words) > 12 and re.search(
            r'\b(then|shall|such|also|allowed|process|through|increased|'
            r'available|directly|reseller|participated|supplier|bidder)\b',
            s, re.IGNORECASE,
        ):
            return False
        # Reject broken PDF fragments that contain "/" or "&" with short surrounding text
        # e.g. "Document/&", "ेता \x01विश\x01F द-तावेज़"
        alpha_only = re.sub(r'[^A-Za-z\s]', '', s).strip()
        alpha_words = [w for w in alpha_only.split() if len(w) >= 3]
        if len(alpha_words) < 1:
            return False
        # Reject lines that are mostly non-alpha (PDF column separators / partial Hindi)
        if len(alpha_only) < len(s) * 0.4:
            return False
        return True

    if not real_headers:
        # No structured consignee table found — return empty rather than
        # scanning the whole document and picking up EMD amounts / prices as pincodes.
        cons_headers_ranges = []
    else:
        cons_headers_ranges = []
        for i, hdr in enumerate(real_headers):
            # Table block: from end of header to start of next real header (or +6000)
            block_start = hdr.end()
            if i + 1 < len(real_headers):
                block_end = real_headers[i + 1].start()
            else:
                block_end = block_start + 6000
            block_end = min(block_end, block_start + 6000)

            # ── Item name: scan backwards from header, skip boilerplate ──
            # Search from the end of the previous real header (or doc start) to
            # the start of this header.
            prev_end  = real_headers[i - 1].end() if i > 0 else 0
            pre_text  = pdf_text[prev_end: hdr.start()]

            item_name = ""
            # Split on newlines for raw text, or on PDF section boundaries for collapsed text
            # Section boundaries in collapsed text: ") " before Hindi text, "Advisory-", etc.
            if "\n" in pre_text:
                segments = pre_text.split("\n")
                for line in reversed(segments):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    # Skip pure Devanagari lines
                    if re.search(r"[\u0900-\u097F]", stripped):
                        continue
                    # Must contain at least one English letter and be ≥ 6 chars
                    if not re.search(r"[A-Za-z]", stripped) or len(stripped) < 6:
                        continue
                    if _ITEM_NAME_SKIP.search(stripped):
                        continue
                    if not _looks_like_item_name(stripped):
                        continue
                    item_name = clean_text(_ITEM_NAME_TRAIL.sub("", stripped))
                    break
            else:
                # Collapsed text: item name appears after qty/days of the previous row.
                # Pattern: digits (qty) space digits (days) space ITEM_NAME (Jमशः...
                # Extract from the previous block's tail if available.
                if i > 0:
                    prev_block_start = real_headers[i - 1].end()
                    prev_block_end   = hdr.start()
                    prev_block = pdf_text[prev_block_start: prev_block_end]
                    # Find the last qty+days pattern: two standalone numbers followed by
                    # an all-caps English item name before Hindi text
                    item_m = re.search(
                        r"\b\d+\s+\d+\s+([A-Z][A-Z0-9\s,\.\-/]{5,100}?)(?:\s*[\(\u0900-\u097F]|\s*$)",
                        prev_block,
                    )
                    if item_m:
                        candidate = clean_text(item_m.group(1)).rstrip(" ,.-")
                        # Strip trailing page numbers like "5 / 19"
                        candidate = re.sub(r'\s+\d+\s*/\s*\d+\s*$', '', candidate).strip()
                        if _looks_like_item_name(candidate) and not _ITEM_NAME_SKIP.search(candidate):
                            item_name = _ITEM_NAME_TRAIL.sub("", candidate)

            cons_headers_ranges.append((block_start, block_end, item_name))

    # ── Parse each table block ──
    for block_start, block_end, item_name in cons_headers_ranges:
        cons_block = pdf_text[block_start:block_end]

        # Track which positions in the block are "used" as address tails of already
        # found rows, so we don't re-parse embedded phone/catalog numbers.
        used_ranges: list[tuple[int, int]] = []

        pin_iter = re.finditer(r"(?<!\d)(\d{6})(?!\d)", cons_block)
        for pin_m in pin_iter:
            pin = pin_m.group(1)

            # Indian pincodes never start with 0
            if pin[0] == "0":
                continue

            # Skip if this position falls inside an already-consumed address range
            if any(start <= pin_m.start() <= end for start, end in used_ranges):
                continue

            # Skip bank / IFSC / financial context
            ctx_start = max(0, pin_m.start() - 150)
            ctx_end   = min(len(cons_block), pin_m.end() + 300)
            context   = cons_block[ctx_start:ctx_end]
            if any(bm.lower() in context.lower() for bm in _BANK_MARKERS):
                continue

            # Skip phone-number and city-postcode context:
            # e.g. "08933-295552", "Mumbai-400074", "DURGAPUR - 713212"
            # Check up to 10 chars before for a dash (with optional space)
            pre_10 = cons_block[max(0, pin_m.start() - 10): pin_m.start()]
            if re.search(r"[\-–]\s*$", pre_10):
                continue   # dash (with optional whitespace) immediately before the 6-digit number
            if re.search(r"Phone|Tel\.?|Mob\.?|Fax|zipcode|zip\s*code",
                         cons_block[max(0, pin_m.start() - 30): pin_m.start()], re.IGNORECASE):
                continue

            # Skip spec/catalog values that appear in comma-separated number lists
            # e.g. "1001 to 2000, ... 100001 to 500000, 500001 to 1000000"
            # Look at 30 chars before (collapse newlines for matching)
            pre_30 = cons_block[max(0, pin_m.start() - 30): pin_m.start()].replace('\n', ' ').strip()
            if re.search(r"(,?\s*\d+\s+to\s*$|\bto\s+\d+\s*,?\s*$|\bto\s*$)", pre_30, re.IGNORECASE):
                continue

            # ── Consignee name: person name between row-number and pincode ──
            # The name appears between the row-number ("1") and the pincode.
            # Stop at any embedded 6-digit number (another pincode in the address).
            pre = cons_block[max(0, pin_m.start() - 250): pin_m.start()]
            name_m = re.search(
                r"(?:\d{1,3}[\s\n]+)([A-Za-z][A-Za-z\s\.]{3,60})\s*$",
                pre,
            )
            consignee_name = clean_text(name_m.group(1)) if name_m else ""

            # ── Address tail after pincode ──
            # Consume the address text. The address ends when we hit a standalone
            # integer (the quantity) after whitespace. "NH2", "C/O1" etc. are
            # part of the address, so we use a smarter stop condition:
            # stop at a digit that is preceded by whitespace/comma and NOT inside a word.
            post = cons_block[pin_m.end(): pin_m.end() + 400]
            # Find where standalone numbers start (qty/days area)
            # A standalone number: preceded by \s or , and followed by \s or end
            addr_end = len(post)
            for num_m in re.finditer(r'(?<=[\s,])(\d+)(?=[\s\n]|$)', post):
                val = int(num_m.group(1))
                # Skip tiny numbers that could be part of road names
                if val > 0 and val != int(pin):
                    addr_end = num_m.start()
                    break
            # Also cap at 200 chars to avoid runaway
            addr_end = min(addr_end, 200)
            addr_tail = clean_text(post[:addr_end])

            # ── Quantity and delivery days ──
            post_addr = post[addr_end:]
            qty = None
            del_days = None
            numbers = re.findall(r"\b(\d[\d,]*)\b", post_addr)
            for num_str in numbers:
                num_clean = re.sub(r",", "", num_str)
                if not num_clean.isdigit():
                    continue
                val = int(num_clean)
                if val == int(pin):
                    continue   # skip the pincode value itself
                if val == 0:
                    continue
                # Sanity: quantity shouldn't be an unrealistic number
                # (prices/EMD amounts can be 6-7+ digits; real qty is usually ≤ 999999)
                if val > 999999:
                    continue
                # Skip 6-digit numbers in post_addr that look like embedded pincodes
                # (e.g. "Mumbai-400074" in address text bleeds into post_addr)
                if len(num_clean) == 6 and num_clean[0] != '0' and qty is None:
                    # Check context in post_addr around this number
                    num_pos = post_addr.find(num_str)
                    pre_ctx = post_addr[max(0, num_pos - 10): num_pos].replace('\n', ' ')
                    # Also check if addr_tail ends with a dash (city-pincode pattern)
                    addr_tail_end = (addr_tail or "").rstrip()
                    if re.search(r"[\-–]$|zipcode|zip\s*code", pre_ctx, re.IGNORECASE) or \
                       addr_tail_end.endswith('-') or addr_tail_end.endswith('–'):
                        continue
                if qty is None:
                    qty = val
                elif del_days is None and val <= 3650:  # delivery days ≤ 10 years
                    del_days = val
                    break

            if qty is not None:
                # Mark from this pincode position to end of qty/days area as consumed
                # so embedded pincodes in the address (e.g. "DURGAPUR - 713212") are skipped
                used_ranges.append((pin_m.start(), pin_m.end() + addr_end + 50))
                consignee_items.append({
                    "item_name":          item_name,
                    "consignee_name":     consignee_name,
                    "consignee_location": f"{pin},{addr_tail}".rstrip(",").strip(),
                    "pincode":            pin,
                    "quantity":           qty,
                    "delivery_days":      del_days,
                })

    # If item_name is empty for any row, fall back to the PDF's item category
    fallback_item_name = _trim_item_tail(_extract_item_category(pdf_text))

    consignee_items_final: list[dict] = []
    for row in consignee_items:
        if not row["item_name"]:
            row = {**row, "item_name": fallback_item_name}
        consignee_items_final.append(row)
    consignee_items = consignee_items_final
    seen_rows: set = set()
    deduped: list[dict] = []
    for row in consignee_items:
        key = (row["pincode"], row["quantity"], row["item_name"])
        if key not in seen_rows:
            seen_rows.add(key)
            deduped.append(row)
    consignee_items = deduped

    # ── 6. POLICY (MII & MSE) ─────────────────────────────────────────────────
    policy: dict = {
        "mii_margin_percent":        None,
        "mii_max_quantity_percent":  None,
        "mse_margin_percent":        None,
        "mse_max_quantity_percent":  None,
    }

    # MII margin
    mii_margin_m = re.search(
        r"(?:MII|Make\s+in\s+India)\s+(?:Margin|Purchase\s+Preference)\s*[:\-]?\s*"
        r"([\d\.]+)\s*%",
        pdf_text, re.IGNORECASE,
    )
    if mii_margin_m:
        try:
            policy["mii_margin_percent"] = float(mii_margin_m.group(1))
        except ValueError:
            pass

    # MII max quantity share
    mii_qty_m = re.search(
        r"(?:MII|Make\s+in\s+India)\s+(?:Maximum\s+)?(?:Quantity|Allocation)\s*[:\-]?\s*"
        r"([\d\.]+)\s*%",
        pdf_text, re.IGNORECASE,
    )
    if mii_qty_m:
        try:
            policy["mii_max_quantity_percent"] = float(mii_qty_m.group(1))
        except ValueError:
            pass

    # MSE margin — two formats:
    # 1. Table cell: "Purchase Preference to MSE OEMs available upto price within L1+X% → 15"
    # 2. Inline prose: "L-1+15% of margin of purchase preference"
    mse_margin_m = (
        re.search(
            r"MSE\s+(?:OEMs?\s+)?(?:available\s+upto\s+price\s+within\s+)?L[-\s]?1\s*\+\s*X\s*%"
            r"[^\n]{0,60}\n\s*([\d\.]+)",
            pdf_text, re.IGNORECASE,
        )
        or re.search(
            r"L[-\s]?1\s*\+\s*([\d\.]+)\s*%\s*(?:of\s+margin|purchase\s+preference|MSE)",
            pdf_text, re.IGNORECASE,
        )
        or re.search(
            r"MSE\s+(?:Margin|Purchase\s+Preference)\s*[:\-]?\s*([\d\.]+)\s*%",
            pdf_text, re.IGNORECASE,
        )
    )
    if mse_margin_m:
        try:
            policy["mse_margin_percent"] = float(mse_margin_m.group(1))
        except ValueError:
            pass

    # MSE max quantity share
    mse_qty_m = re.search(
        r"MSE\s+(?:Maximum\s+)?(?:Quantity|Allocation)\s*[:\-]?\s*([\d\.]+)\s*%",
        pdf_text, re.IGNORECASE,
    )
    if mse_qty_m:
        try:
            policy["mse_max_quantity_percent"] = float(mse_qty_m.group(1))
        except ValueError:
            pass

    return {
        "timeline":        timeline,
        "eligibility":     eligibility,
        "ra_rules":        ra_rules,
        "financials":      financials,
        "consignee_items": consignee_items,
        "policy":          policy,
    }
