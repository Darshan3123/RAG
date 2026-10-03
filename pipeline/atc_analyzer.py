# =========================================================================
# pipeline/atc_analyzer.py
# High-Accuracy ATC (Additional Terms and Conditions) Compliance Analyzer
# =========================================================================
"""
Modular ATC Compliance Analysis Module for GeM Bids.

Extracts:
  1. Standard Documents Required
  2. Clarified ATC Documents & Mandatory Uploads
  3. Exemption Documents Required (MSE & Startup)
  4. Physical Submissions (Offline Instruments, Payee, Payable At, Deadlines)
  5. Key Commercial Terms & Conditions

Supports:
  - Google Gemini API (Default, 1M token context window, zero local GPU required)
  - Local Qwen / llama-server fallback
  - External ATC document downloads (PDFs) via PyMuPDF in-memory parsing
  - Structured output parsing (Markdown -> clean JSON checklist)
  - Automatic persistence of <bid_no>_ATC.md and JSON enrichment
"""

import os
import re
import json
import time
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
import requests
from bs4 import BeautifulSoup

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

from utils.logger import get_logger

log = get_logger("atc_analyzer")

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
LLM_PROVIDER = os.getenv("ATC_LLM_PROVIDER", "gemini").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()

LLAMA_SERVER_URL = os.getenv("LLAMA_SERVER_URL", "http://localhost:8080").strip()
CHAT_ENDPOINT = f"{LLAMA_SERVER_URL}/v1/chat/completions"

REQUIRED_DOCS_HEADERS = [
    "Document required from seller",
    "विक्रेता से आवश्यक दस्तावेज",
]

ATC_START_MARKERS = [
    "Buyer Added Bid Specific Terms and Conditions",
    "क्रेता ने बोली विशिष्ट अतिरिक्त नियम",
    "Buyer Added Bid Specific Additional Terms and Conditions",
]

ATC_END_MARKERS = [
    "अस्वीकरण/Disclaimer",
    "Disclaimer",
]

ATC_PDF_LINK_NAMES = [
    "buyer uploaded atc document",
    "atc document",
]

# ---------------------------------------------------------------------------
# PROMPT DEFINITION
# ---------------------------------------------------------------------------
ATC_ANALYSIS_SYSTEM_PROMPT = """Role & Objective:
You are an expert Procurement and Tender Document Analyst. Your task is to analyze government bid documents, clarify exact document requirements by cross-referencing placeholders with the ATC text, and extract actionable requirements into a highly structured, scannable checklist.

Input Format:
You will be provided with text divided into two sections, separated by a line of equals signs (======):
1. Top Section: "Document required from seller" (a comma-separated list of required documents).
2. Bottom Section: "Additional Terms and Conditions" (ATC) text — this may be the raw ATC text, or a compacted set of evidence sentences extracted from it.

Internal Process (do this before writing any output — do not show these steps in your final answer):

STEP 1 — ENUMERATE: Read the entire ATC text from start to finish, clause by clause. List every distinct obligation, instruction, requirement, deadline, or document mention placed on the bidder, in the order it appears — including anything embedded inside a clause about a different main topic. Capture everything, including minor procedural instructions.

STEP 2 — CATEGORIZE: Using the full list from Step 1, sort every item into exactly one of the five sections below. Every item enumerated in Step 1 must appear somewhere in the final output. Each item belongs in exactly one section — do not repeat the same item across multiple sections.

STEP 3 — SILENT FIX-UP (mandatory, before writing final output — perform silently, output nothing about this step):
a. Section 1: delete any bullet containing "(Requested in ATC)". If none remain, Section 1's body is just "* None specified in the provided text."
b. Section 2: any placeholder tagged "(Requested in ATC)" — whatever its name (Certificate, Additional Doc 1, Additional Doc 2, or any other label) — is never resolved using the exemption-eligibility sentence that follows the top-section list. That sentence belongs to Section 3 only.
c. Section 3: never combine "None specified" with a (Explicit)/(Inferred) tag in the same line. Always output a real document name with exactly one tag.
d. Section 4: "In Favor Of" = payee on the instrument only, never a mailing recipient.
These four corrections happen silently in your draft. They are never described, explained, or mentioned in the output.

Formatting & Output Rules:
- CRITICAL CONCISENESS: Do NOT write full sentences for document lists. Do NOT use conversational filler (e.g., "Here is the summary...", "This placeholder requires..."). Output the data directly.
- ABSOLUTE RULE — NO META-COMMENTARY: The output must contain ONLY the five "###" headings and their bullets. Never include the words "Note:", "Final output:", or any explanation of a decision, exclusion, or inference. Never use symbols like checkmarks or crosses. Never explain why something was included, excluded, or inferred — the tags "(Explicit)" and "(Inferred)" in Section 3 are the ONLY allowed annotations anywhere in the output. If you catch yourself about to write a sentence explaining your own reasoning, delete that sentence before outputting.
- Do NOT output Steps 1-3 or any internal reasoning. Output only the five formatted sections below.
- Use Markdown extensively. Use ### for main headings and * for bulleted lists.
- Use **Bold Text** to highlight key entities (document names, placeholders, deadlines, percentages, and authorities).
- If multiple formats apply to one category, separate them with commas.
- If a section has no relevant data in the provided text, output "None specified in the provided text." strictly under that heading — except Section 3, which follows its own rule below and must never use this fallback when an exemption category is present in the top section.

Required Output Structure:
Categorize the extracted information exactly into the following five sections:

### 1. Standard Documents Required
From the top section's comma-separated list, output only items that do NOT contain "(Requested in ATC)". Items containing that phrase are never output here (they belong in Section 2 only).
* [Exact Document Name]

### 2. Clarified ATC Documents & Mandatory Uploads
Analyze the top section for every placeholder tagged "(Requested in ATC)" — regardless of its label (e.g. "Certificate", "Additional Doc 1", "Additional Doc 2", or any other name). For each one, read the bottom ATC text and deduce EXACTLY what specific certificate or document is being requested, based on a clause that actually describes a document — not the exemption-eligibility sentence. Also, list any other mandatory certificates, registrations, declarations, undertakings, or digital uploads mentioned anywhere in the ATC text, even if mentioned only in passing within a clause about another topic.
* **[Placeholder Name from Top Section]**: [Exact document name 1, Exact document name 2]
* **[Other Upload Required in ATC]**: [Brief description/criteria, e.g., "last 3 years", "CA certified"]

### 3. Exemption Documents Required
Look for exemption clauses in the top list (e.g., "*In case any bidder is seeking exemption from Experience / Turnover Criteria..."). Determine what document is required to claim each exemption:
- If the ATC text explicitly names the required document, use that exact name and mark it (Explicit).
- If the ATC text mentions the exemption category but does not specify a document, you MUST name the standard document conventionally required under GeM/government procurement practice (e.g. Udyam/MSE Registration Certificate for MSE exemption, DPIIT Startup Recognition Certificate for Start-up exemption) and mark it (Inferred — not explicit in ATC text). A named document is always required in this section when the exemption clause is present in the top section; "None specified" is never a valid entry here in that case.
* **Proof for Exemption (MSEs)**: [Exact certificate name] (Explicit/Inferred)
* **Proof for Exemption (Start-ups)**: [Exact certificate name] (Explicit/Inferred)

### 4. Physical Submissions (Offline)
Extract any physical items, hard copies, or financial instruments (like EMD/PBG) mentioned in the ATC text that must be mailed or delivered offline. If multiple clauses describe the same underlying financial instrument or submission, treat them as ONE item and combine all details into a single entry — do not split one submission into multiple bullets.
- "Payable At" must always be a bank name or bank location tied to the instrument itself — never a mailing/delivery address.
- "In Favor Of" must always be the payee named on the instrument itself — never a mailing/delivery recipient. If the payee and the delivery recipient are different parties, keep them in separate fields.
* **[Item to Deliver]**: [Brief description]
  * Deadline: [e.g., Within 5 days of Bid End]
  * In Favor Of: [Payee name — from the instrument, not the delivery address]
  * Payable At: [Bank/Location]
  * Delivery Address: [Physical mailing address/recipient, if different from payee]

### 5. Key Commercial Terms & Conditions to Follow
Extract strict operational, pricing, or compliance rules the bidder must adhere to from the ATC text. Include minor procedural instructions as well (e.g. required envelope superscription, required fields in a payment portal's remarks section, specific codes to be used).
* **[Topic, e.g., GST / Option Clause / Scope of Supply]**: [Clear, concise explanation of the rule, penalty, or requirement]
"""

# ---------------------------------------------------------------------------
# EXTRACTION HELPERS
# ---------------------------------------------------------------------------
def extract_required_docs_text(markdown_text: str) -> str:
    """Extract the 'Document required from seller' table row from markdown."""
    if not markdown_text:
        return ""

    soup = BeautifulSoup(markdown_text, "html.parser")
    for row in soup.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) >= 2:
            key = cols[0].text.strip()
            for header in REQUIRED_DOCS_HEADERS:
                if header.lower() in key.lower():
                    val = cols[1].text.strip()
                    return f"{key} : {val}"

    # Regex fallback for non-table markdown text
    for header in REQUIRED_DOCS_HEADERS:
        m = re.search(rf"{header}[^\n:]*[:\-|]+\s*([^\n]+)", markdown_text, re.IGNORECASE)
        if m:
            return f"{header} : {m.group(1).strip()}"

    return "Document required from seller : None specified in main document"


def extract_embedded_atc_text(markdown_text: str) -> str:
    """Extract embedded ATC text between start and end markers."""
    if not markdown_text:
        return ""

    start_idx = -1
    matched_start_len = 0
    for marker in ATC_START_MARKERS:
        idx = markdown_text.find(marker)
        if idx != -1:
            start_idx = idx
            matched_start_len = len(marker)
            break

    if start_idx == -1:
        return ""

    content_start_idx = start_idx + matched_start_len
    end_idx = -1
    for marker in ATC_END_MARKERS:
        idx = markdown_text.find(marker, content_start_idx)
        if idx != -1:
            if end_idx == -1 or idx < end_idx:
                end_idx = idx

    if end_idx != -1:
        extracted = markdown_text[content_start_idx:end_idx].strip()
    else:
        # If no end marker is found, take up to 25,000 characters
        extracted = markdown_text[content_start_idx:content_start_idx + 25000].strip()

    # Clean out boilerplate hyperlink text
    extracted = re.sub(
        r"Buyer uploaded ATC document\s*\[?Click here to view the file\]?\([^)]*\)?",
        "", extracted, flags=re.IGNORECASE
    )
    extracted = extracted.replace("Buyer uploaded ATC document Click here to view the file", "").strip()

    return extracted


def extract_external_pdf_text(pdf_url: str) -> str:
    """Download and extract text from an external ATC PDF in memory."""
    if not pdf_url or not fitz:
        return ""

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(pdf_url, timeout=20, headers=headers)
        if resp.status_code != 200 or not resp.content:
            return ""

        # Verify not an HTML login redirect
        content_type = resp.headers.get("Content-Type", "").lower()
        if "html" in content_type:
            return ""

        doc = fitz.open(stream=resp.content, filetype="pdf")
        pages_text = []
        for i in range(len(doc)):
            page_t = doc[i].get_text("text").strip()
            if page_t:
                pages_text.append(f"--- [Page {i + 1}] ---\n{page_t}")
        doc.close()
        return "\n\n".join(pages_text)
    except Exception as e:
        log.warning(f"Could not extract external ATC PDF from {pdf_url}: {e}")
        return ""


# ---------------------------------------------------------------------------
# LLM INFERENCE CLIENTS
# ---------------------------------------------------------------------------
def call_gemini(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4000,
    temperature: float = 0.1,
    retries: int = 3
) -> str:
    """Send request to Google Gemini API with rate-limiting backoff."""
    if not GEMINI_API_KEY:
        log.error("GEMINI_API_KEY is not set in environment or .env.")
        return ""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_prompt}]
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
    }

    if system_prompt:
        payload["system_instruction"] = {
            "parts": [{"text": system_prompt}]
        }

    headers = {"Content-Type": "application/json"}

    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=120)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
                return ""
            elif resp.status_code == 429:
                wait_time = attempt * 5
                log.warning(f"Gemini API rate limited (429). Retrying in {wait_time}s (attempt {attempt}/{retries})...")
                time.sleep(wait_time)
            else:
                log.error(f"Gemini API error (HTTP {resp.status_code}): {resp.text[:300]}")
                if attempt < retries and resp.status_code >= 500:
                    time.sleep(attempt * 3)
                else:
                    return ""
        except requests.exceptions.RequestException as e:
            log.warning(f"Gemini API connection error (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(attempt * 3)
            else:
                return ""

    return ""


def call_local_qwen(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2000
) -> str:
    """Send request to local llama.cpp / Qwen server."""
    payload = {
        "model": "local-qwen3-4b",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    try:
        resp = requests.post(CHAT_ENDPOINT, json=payload, timeout=180)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.error(f"llama-server call failed at {CHAT_ENDPOINT}: {e}")
        return ""


def call_atc_llm(system_prompt: str, user_prompt: str) -> str:
    """Dispatch LLM call according to ATC_LLM_PROVIDER."""
    provider = os.getenv("ATC_LLM_PROVIDER", LLM_PROVIDER).strip().lower()
    if provider == "gemini":
        return call_gemini(system_prompt, user_prompt)
    elif provider in ("local_qwen", "llama", "local"):
        return call_local_qwen(system_prompt, user_prompt)
    else:
        # Default fallback to Gemini
        return call_gemini(system_prompt, user_prompt)


# ---------------------------------------------------------------------------
# OUTPUT PARSER (MARKDOWN -> STRUCTURED DICTIONARY)
# ---------------------------------------------------------------------------
def parse_atc_markdown_to_dict(markdown_output: str) -> Dict[str, Any]:
    """
    Parse the 5-section markdown checklist produced by the LLM into
    a clean, structured Python dictionary.
    """
    res = {
        "standard_documents": [],
        "clarified_atc_documents": [],
        "exemption_documents": [],
        "physical_submissions": [],
        "commercial_terms": [],
    }

    if not markdown_output:
        return res

    # Section patterns
    section_patterns = [
        (1, r"###\s*1\.\s*Standard Documents Required\s*\n(.*?)(?=###|\Z)"),
        (2, r"###\s*2\.\s*Clarified ATC Documents[^\n]*\n(.*?)(?=###|\Z)"),
        (3, r"###\s*3\.\s*Exemption Documents Required\s*\n(.*?)(?=###|\Z)"),
        (4, r"###\s*4\.\s*Physical Submissions[^\n]*\n(.*?)(?=###|\Z)"),
        (5, r"###\s*5\.\s*Key Commercial Terms[^\n]*\n(.*?)(?=###|\Z)"),
    ]

    sections_text = {}
    for sec_num, pat in section_patterns:
        m = re.search(pat, markdown_output, re.DOTALL | re.IGNORECASE)
        sections_text[sec_num] = m.group(1).strip() if m else ""

    # 1. Standard Documents
    sec1 = sections_text.get(1, "")
    for line in sec1.splitlines():
        line = line.strip()
        if line.startswith("*") or line.startswith("-"):
            doc = re.sub(r"^[\*\-]\s*", "", line).strip()
            if doc and not doc.lower().startswith("none specified"):
                res["standard_documents"].append(doc)

    # 2. Clarified ATC Documents
    sec2 = sections_text.get(2, "")
    for line in sec2.splitlines():
        line = line.strip()
        if (line.startswith("*") or line.startswith("-")) and "**" in line:
            m = re.match(r"^[\*\-]\s*\*\*(.*?)\*\*\s*[:\-]\s*(.*)", line)
            if m:
                placeholder = m.group(1).strip()
                details = m.group(2).strip()
                res["clarified_atc_documents"].append({
                    "placeholder": placeholder,
                    "requirement": details
                })
        elif (line.startswith("*") or line.startswith("-")):
            doc = re.sub(r"^[\*\-]\s*", "", line).strip()
            if doc and not doc.lower().startswith("none specified"):
                res["clarified_atc_documents"].append({
                    "placeholder": "Requirement",
                    "requirement": doc
                })

    # 3. Exemption Documents
    sec3 = sections_text.get(3, "")
    for line in sec3.splitlines():
        line = line.strip()
        if line.startswith("*") or line.startswith("-"):
            m = re.match(r"^[\*\-]\s*\*\*(.*?)\*\*\s*[:\-]\s*(.*)", line)
            if m:
                cat = m.group(1).strip()
                val = m.group(2).strip()
                is_explicit = "explicit" in val.lower()
                clean_val = re.sub(r"\(Explicit\)|\(Inferred[^\)]*\)", "", val, flags=re.IGNORECASE).strip()
                res["exemption_documents"].append({
                    "category": cat,
                    "required_document": clean_val,
                    "is_explicit": is_explicit
                })

    # 4. Physical Submissions
    sec4 = sections_text.get(4, "")
    current_sub = None
    for line in sec4.splitlines():
        stripped = line.strip()
        if (stripped.startswith("*") or stripped.startswith("-")) and line.startswith(("*", "-")):
            m = re.match(r"^[\*\-]\s*\*\*(.*?)\*\*\s*[:\-]?\s*(.*)", stripped)
            if m:
                item_name = m.group(1).strip()
                desc = m.group(2).strip()
                current_sub = {
                    "item": item_name,
                    "description": desc,
                    "deadline": "",
                    "in_favor_of": "",
                    "payable_at": "",
                    "delivery_address": "",
                }
                res["physical_submissions"].append(current_sub)
        elif current_sub and (stripped.startswith("*") or stripped.startswith("-")):
            # Sub-bullet details
            sub_m = re.match(r"^[\*\-]\s*([a-zA-Z\s]+)[:\-]\s*(.*)", stripped)
            if sub_m:
                k = sub_m.group(1).strip().lower()
                v = sub_m.group(2).strip()
                if "deadline" in k:
                    current_sub["deadline"] = v
                elif "favor" in k:
                    current_sub["in_favor_of"] = v
                elif "payable" in k:
                    current_sub["payable_at"] = v
                elif "address" in k:
                    current_sub["delivery_address"] = v

    # 5. Commercial Terms
    sec5 = sections_text.get(5, "")
    for line in sec5.splitlines():
        line = line.strip()
        if (line.startswith("*") or line.startswith("-")) and "**" in line:
            m = re.match(r"^[\*\-]\s*\*\*(.*?)\*\*\s*[:\-]\s*(.*)", line)
            if m:
                topic = m.group(1).strip()
                rule = m.group(2).strip()
                res["commercial_terms"].append({
                    "topic": topic,
                    "rule": rule
                })
        elif line.startswith("*") or line.startswith("-"):
            rule = re.sub(r"^[\*\-]\s*", "", line).strip()
            if rule and not rule.lower().startswith("none specified"):
                res["commercial_terms"].append({
                    "topic": "General Term",
                    "rule": rule
                })

    return res


# ---------------------------------------------------------------------------
# PRIMARY PIPELINE FUNCTION
# ---------------------------------------------------------------------------
def analyze_bid_atc(
    bid_no: str,
    markdown_text: str,
    hyperlinks: Optional[List[Dict[str, str]]] = None,
    save_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run end-to-end ATC compliance analysis on a bid.

    Args:
        bid_no (str): Bid or RA identification number.
        markdown_text (str): Full markdown conversion of the bid PDF.
        hyperlinks (list, optional): List of hyperlink dicts with 'name' and 'url'.
        save_dir (str, optional): Directory to save the <bid_no>_ATC.md artifact.

    Returns:
        dict: Complete structured result including raw markdown and structured checklist.
    """
    safe_bid_no = (bid_no or "UNKNOWN").replace("/", "_")
    log.info(f"Starting ATC analysis for {safe_bid_no}...")

    # 1. Extract required docs header
    req_docs = extract_required_docs_text(markdown_text)

    # 2. Extract embedded ATC text
    embedded_atc = extract_embedded_atc_text(markdown_text)

    # 3. Check for external ATC document hyperlink
    external_atc = ""
    if hyperlinks:
        for link in hyperlinks:
            name = str(link.get("name", "")).lower()
            url = link.get("url")
            if any(k in name for k in ATC_PDF_LINK_NAMES) and url:
                log.info(f"Found external ATC document link: {url}")
                external_atc = extract_external_pdf_text(url)
                if external_atc:
                    log.info(f"Extracted {len(external_atc)} chars from external ATC document.")
                break

    # Combine ATC text
    all_atc_parts = []
    if embedded_atc:
        all_atc_parts.append(f"--- [Embedded Bid ATC Terms] ---\n{embedded_atc}")
    if external_atc:
        all_atc_parts.append(f"--- [External Buyer Uploaded ATC Document] ---\n{external_atc}")

    combined_atc = "\n\n".join(all_atc_parts).strip()

    if not combined_atc:
        log.info(f"No ATC content found for {safe_bid_no}. Skipping LLM analysis.")
        return {
            "status": "skipped_no_atc",
            "bid_no": safe_bid_no,
            "has_atc": False,
            "raw_markdown": "",
            "checklist": {
                "standard_documents": [],
                "clarified_atc_documents": [],
                "exemption_documents": [],
                "physical_submissions": [],
                "commercial_terms": [],
            },
            "error": None
        }

    # Prepare prompt
    user_prompt = (
        f"Document required from seller:\n{req_docs}\n\n"
        f"======\n\n"
        f"Additional Terms and Conditions:\n{combined_atc}\n"
    )

    t0 = time.time()
    raw_markdown = call_atc_llm(ATC_ANALYSIS_SYSTEM_PROMPT, user_prompt)
    elapsed = round(time.time() - t0, 2)

    if not raw_markdown:
        log.warning(f"ATC LLM analysis returned empty response for {safe_bid_no}.")
        return {
            "status": "error",
            "bid_no": safe_bid_no,
            "has_atc": True,
            "raw_markdown": "",
            "checklist": {},
            "error": "LLM returned empty response",
            "elapsed_seconds": elapsed
        }

    # Clean markdown
    raw_markdown = re.sub(r"^\s*---\s*$", "", raw_markdown, flags=re.MULTILINE).strip()

    # Parse into structured dictionary
    structured_checklist = parse_atc_markdown_to_dict(raw_markdown)

    # Save artifact if directory is provided
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
        atc_md_path = os.path.join(save_dir, f"{safe_bid_no}_ATC.md")
        try:
            with open(atc_md_path, "w", encoding="utf-8") as f:
                f.write(raw_markdown)
            log.info(f"Saved ATC analysis markdown to {atc_md_path}")
        except Exception as e:
            log.warning(f"Could not save ATC markdown to {atc_md_path}: {e}")

    log.info(f"ATC analysis completed for {safe_bid_no} in {elapsed}s.")
    return {
        "status": "success",
        "bid_no": safe_bid_no,
        "has_atc": True,
        "elapsed_seconds": elapsed,
        "raw_markdown": raw_markdown,
        "checklist": structured_checklist,
        "error": None
    }
