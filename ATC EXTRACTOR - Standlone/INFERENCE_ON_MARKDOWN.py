"""
=========================================================================
USAGE
=========================================================================
Run from the command line, pointing at a directory that contains the
tender directories/files (.json and .pdf):

    python INFERENCE_ON_MARKDOWN.py <path_to_tender_directory>

Example:

    python INFERENCE_ON_MARKDOWN.py TEST-DATA
"""

import sys
import os
import re
import json
import time
import multiprocessing

import io
import tempfile
import requests
import pymupdf
import docx
from tabulate import tabulate
from vertexai.preview import tokenization



# =========================================================================
# CONFIG & ENVIRONMENT
# =========================================================================
try:
    from dotenv import load_dotenv
    # Load .env directly from the main project root ("GEM RAG Development")
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    _env_path = os.path.join(_project_root, ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
except Exception as e:
    print(f"[!] Warning: Could not load .env: {e}")

from core.mistral_ocr_manager import (
    process_pdf_to_markdown,
)

ANALYSIS_OUTPUT_DIR = "OUTPUT"
CHUNKS_OUTPUT_DIR = "CHUNKS"

# Gemini API configuration loaded from GEM RAG Development .env
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "").strip()

# Target Chunk & Context Budgeting for Map-Red()uce flow (aligned with Gemini 2.5 Flash / Flash Lite)
CHUNK_CATEGORIZING_MAX_INPUT_TOKENS = 1000000
CHUNK_CATEGORIZING_MAX_OUTPUT_TOKENS = 65536
FINAL_STAGE_INPUT_TOKENS = 1000000
FINAL_STAGE_OUTPUT_TOKENS = 65536

if not GEMINI_API_KEY:
    print("[!] Warning: GEMINI_API_KEY not found in .env. Please configure GEMINI_API_KEY in GEM RAG Development/.env.")

print(f"[*] ATC Extractor configured: Engine=GEMINI MAP-REDUCE (model='{GEMINI_MODEL}')")

# =========================================================================
# LOCAL TOKENIZER SETUP (VERTEX AI TOKENIZATION)
# =========================================================================
_tokenizer_model_id = "gemini-1.5-flash-002" if "flash" in GEMINI_MODEL.lower() else "gemini-1.5-pro-002"
_gemini_tokenizer = tokenization.get_tokenizer_for_model(_tokenizer_model_id)
print(f"[*] Initialized local Vertex AI tokenizer: '{_tokenizer_model_id}'")


def count_tokens(text: str) -> int:
    """Return precise token count via local Gemini tokenizer."""
    if not text:
        return 0
    return _gemini_tokenizer.count_tokens(text).total_tokens


# =========================================================================
# EXTRACTION-STAGE CONFIG
# =========================================================================
ATC_SECTION_START_MARKER = "Buyer Added Bid Specific Terms and Conditions"
ATC_SECTION_END_MARKER = "Disclaimer"
ATC_PDF_LINK_NAME = "Buyer uploaded ATC document"


# =========================================================================
# PROGRESS SPINNER
# =========================================================================
def _run_spinner(description, stop_event):
    start_time = time.time()
    spinner = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    idx = 0
    
    if len(description) > 70:
        description = description[:67] + "..."
        
    while not stop_event.is_set():
        elapsed = time.time() - start_time
        sys.stdout.write(f"\r\033[2K{spinner[idx]} {description} | Elapsed time: {elapsed:.1f}s")
        sys.stdout.flush()
        idx = (idx + 1) % len(spinner)
        time.sleep(0.1)


class ProgressTimer:
    def __init__(self, description):
        self.description = description
        self._stop_event = multiprocessing.Event()
        self._process = None
        self.start_time = None

    def start(self):
        self.start_time = time.time()
        self._process = multiprocessing.Process(target=_run_spinner, args=(self.description, self._stop_event))
        self._process.daemon = True
        self._process.start()

    def stop(self):
        self._stop_event.set()
        if self._process:
            self._process.join()
        elapsed = time.time() - self.start_time
        
        desc = self.description
        if len(desc) > 70:
            desc = desc[:67] + "..."
            
        sys.stdout.write(f"\r\033[2K✅ {desc} | Completed in {elapsed:.1f}s\n")
        sys.stdout.flush()


# =========================================================================
# TOKEN / TIMING USAGE TRACKING
# =========================================================================
TOKEN_RECORDS = []
GRAND_TOTAL_SECONDS = 0.0


def record_call(label: str, system_prompt: str, user_prompt: str, output_text: str, elapsed_seconds: float) -> None:
    global GRAND_TOTAL_SECONDS
    in_tokens = count_tokens(system_prompt) + count_tokens(user_prompt)
    out_tokens = count_tokens(output_text)
    TOKEN_RECORDS.append((label, in_tokens, out_tokens, elapsed_seconds))
    GRAND_TOTAL_SECONDS += elapsed_seconds


# Pricing: $0.15 per 1M input tokens, $1.50 per 1M output tokens
INPUT_COST_PER_MILLION = 0.15
OUTPUT_COST_PER_MILLION = 1.50


def calculate_cost(input_tokens: int, output_tokens: int) -> float:
    input_cost = (input_tokens / 1_000_000) * INPUT_COST_PER_MILLION
    output_cost = (output_tokens / 1_000_000) * OUTPUT_COST_PER_MILLION
    return input_cost + output_cost


def print_token_table(records, title: str) -> None:
    if not records:
        return

    headers = ["Stage", "Input Tokens", "Output Tokens", "Time (s)", "Cost ($)"]
    rows = []
    for label, i, o, t in records:
        cost = calculate_cost(i, o)
        rows.append((label, f"{i:,}", f"{o:,}", f"{t:.2f}", f"${cost:.6f}"))

    total_in = sum(i for _, i, _, _ in records)
    total_out = sum(o for _, _, o, _ in records)
    total_time = sum(t for _, _, _, t in records)
    total_cost = calculate_cost(total_in, total_out)

    rows.append((
        "TOTAL",
        f"{total_in:,}",
        f"{total_out:,}",
        f"{total_time:.2f}",
        f"${total_cost:.6f}"
    ))

    print(f"\n    Token & Cost Summary — {title}")
    table_str = tabulate(rows, headers=headers, tablefmt="fancy_grid", maxcolwidths=[45, None, None, None, None])
    for line in table_str.splitlines():
        print(f"    {line}")
    print(f"    💵 Total Cost: ${total_cost:.6f}  (Input: {total_in:,} @ ${INPUT_COST_PER_MILLION}/1M | Output: {total_out:,} @ ${OUTPUT_COST_PER_MILLION}/1M)\n")


# =========================================================================
# GEMINI API CALL
# =========================================================================
def call_gemini(system_prompt: str, user_prompt: str, max_tokens: int,
                temperature: float = 0.1, require_json: bool = False, retries: int = 3) -> str:
    if not GEMINI_API_KEY:
        print("    [!] Error: GEMINI_API_KEY is not set. Please set it in .env or environment.")
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
        
    if require_json:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    headers = {"Content-Type": "application/json"}

    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=180)
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
                print(f"    [!] Gemini rate limited (429). Retrying in {wait_time}s (attempt {attempt}/{retries})...")
                time.sleep(wait_time)
            else:
                print(f"    [-] Gemini API returned HTTP {resp.status_code}: {resp.text[:300]}")
                if attempt < retries and resp.status_code >= 500:
                    time.sleep(attempt * 2)
                else:
                    return ""
        except requests.exceptions.RequestException as e:
            print(f"    [-] Gemini network error (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(attempt * 2)
            else:
                return ""

    return ""


def timed_gemini_call(spinner_label: str, record_label: str, system_prompt: str, user_prompt: str,
                      max_tokens: int, require_json: bool = False) -> str:
    _t0 = time.time()
    timer = ProgressTimer(spinner_label)
    timer.start()
    result = call_gemini(system_prompt, user_prompt, max_tokens=max_tokens, require_json=require_json)
    timer.stop()
    record_call(record_label, system_prompt, user_prompt, result, time.time() - _t0)
    return result


# =========================================================================
# PROMPTS
# =========================================================================
ANALYSIS_SYSTEM_PROMPT = """Role & Objective:
You are an expert Procurement and Tender Document Analyst. Your task is to analyze government bid documents, clarify exact document requirements by cross-referencing placeholders with the ATC text, and extract actionable requirements into a highly structured, scannable checklist.

Input Format:
You will be provided with text divided into two sections, separated by a line of equals signs (======):
1. Top Section: "Document required from seller" (a comma-separated list of required documents).
2. Bottom Section: "Additional Terms and Conditions" (ATC) text — this may be the raw ATC text, or a compacted set of evidence sentences extracted from it. Treat it the same either way.

Internal Process (do this before writing any output — do not show these steps in your final answer):

STEP 1 — ENUMERATE: Read the entire ATC text from start to finish, clause by clause. List every distinct obligation, instruction, requirement, deadline, or document mention placed on the bidder, in the order it appears — including anything embedded inside a clause about a different main topic. Capture everything, including minor procedural instructions.

STEP 2 — CATEGORIZE: Using the full list from Step 1, sort every item into exactly one of the five sections below. Every item enumerated in Step 1 must appear somewhere in the final output. Each item belongs in exactly one section — do not repeat the same item across multiple sections.

STEP 3 — SILENT FIX-UP (mandatory, before writing final output — perform silently, output nothing about this step):
a. Section 1: delete any bullet containing "(Requested in ATC)". If none remain, Section 1's body is just "* None specified in the provided text."
b. Section 2: any placeholder tagged "(Requested in ATC)" — whatever its name (Certificate, Additional Doc 1, Additional Doc 2, or any other label) — is never resolved using the exemption-eligibility sentence that follows the top-section list. That sentence belongs to Section 3 only.
c. Section 3: always output the exact document name without any annotations or parenthetical tags like (Explicit) or (Inferred).
d. Section 4: "In Favor Of" = payee on the instrument only, never a mailing recipient.
These four corrections happen silently in your draft. They are never described, explained, or mentioned in the output.

Formatting & Output Rules:
- CRITICAL CONCISENESS: Do NOT write full sentences for document lists. Do NOT use conversational filler (e.g., "Here is the summary...", "This placeholder requires..."). Output the data directly.
- ABSOLUTE RULE — NO META-COMMENTARY: Output STRICTLY valid JSON without markdown wrapping (no ```json or ```). Never include conversational explanations, decision reasoning, or symbols like ❌ or ✅. Never explain why something was included, excluded, or inferred. Do NOT include annotations like "(Explicit)" or "(Inferred)". If you catch yourself about to write a sentence explaining your own reasoning, delete that sentence before outputting.
- Do NOT output Steps 1-3 or any internal reasoning.
- Output a single JSON object containing EXACTLY the five keys specified below. Each key must map to an array of clean string items.
- If a section has no relevant data in the provided text, its array must contain strictly one string: ["None specified in the provided text."] — except Section 3, which follows its own rule below and must never use this fallback when an exemption category is present in the top section.

Required Output Structure:
Output strictly a valid JSON object matching this exact schema:
{
  "1. Standard Documents Required": [
    "string"
  ],
  "2. Clarified ATC Documents & Mandatory Uploads": [
    "Placeholder Name (Requested in ATC): Exact Document Name"
  ],
  "3. Exemption Documents Required": [
    "Proof for Exemption (MSEs): Exact Certificate Name",
    "Proof for Exemption (Start-ups): Exact Certificate Name"
  ],
  "4. Physical Submissions (Offline)": [
    {
      "Item": "string",
      "Deadline": "string",
      "In Favor Of": "string",
      "Payable At": "string",
      "Delivery Address": "string"
    }
  ],
  "5. Key Commercial Terms & Conditions to Follow": [
    "Topic: Clear, concise explanation of the rule, penalty, or requirement"
  ]
}

Category Rules & Examples:

1. Standard Documents Required
From the top section's comma-separated list, output only items that do NOT contain "(Requested in ATC)". Items containing that phrase are never output here (they belong in Section 2 only).
Example Input: "PAN Card, GSTIN Copy, Certificate (Requested in ATC)" → Output in array: ["PAN Card", "GSTIN Copy"]
Example Input: "Certificate (Requested in ATC)" → Output in array: ["None specified in the provided text."]

2. Clarified ATC Documents & Mandatory Uploads
Analyze the top section for every placeholder tagged "(Requested in ATC)" — regardless of its label (e.g. "Certificate", "Additional Doc 1", "Additional Doc 2", or any other name). For each one, read the bottom ATC text and deduce EXACTLY what specific certificate or document is being requested, based on a clause that actually describes a document — not the exemption-eligibility sentence. Also, list any other mandatory certificates, registrations, declarations, undertakings, or digital uploads mentioned anywhere in the ATC text, even if mentioned only in passing within a clause about another topic.
Format each item as a string:
- "Placeholder Name (Requested in ATC): Exact Document Name"
- "Other Upload Required in ATC: Brief description/criteria (e.g., last 3 years, CA certified)"

3. Exemption Documents Required
Look for exemption clauses in the top list (e.g., "*In case any bidder is seeking exemption from Experience / Turnover Criteria..."). Determine what document is required to claim each exemption:
- If the ATC text explicitly names the required document, use that exact name.
- If the ATC text mentions the exemption category but does not specify a document, you MUST name the standard document conventionally required under GeM/government procurement practice (e.g. "Udyam Registration Certificate" for MSE exemption, "DPIIT Startup Recognition Certificate" for Start-up exemption). A named document is always required in this section when the exemption clause is present in the top section; "None specified" is never a valid entry here in that case.
- Do NOT append "(Explicit)" or "(Inferred)" tags to the certificate name. Output ONLY the clean certificate name.
Format each item as a string:
- "Proof for Exemption (MSEs): Exact Certificate Name"
- "Proof for Exemption (Start-ups): Exact Certificate Name"

4. Physical Submissions (Offline)
Extract any physical items, hard copies, or financial instruments (like EMD/PBG) mentioned in the ATC text that must be mailed or delivered offline. If multiple clauses describe the same underlying financial instrument or submission, treat them as ONE item and combine all details into a single JSON object — do not split one submission into multiple entries.
- "Payable At" must always be a bank name or bank location tied to the instrument itself — never a mailing/delivery address.
- "In Favor Of" must always be the payee named on the instrument itself — never a mailing/delivery recipient. If the payee and the delivery recipient are different parties, keep them in separate fields.
Format:
- Each submission must be a structured JSON object:
  {
    "Item": "e.g. Original EMD Demand Draft / PBG / Hard copy sample",
    "Deadline": "e.g. Within 5 days of bid end date",
    "In Favor Of": "Payee name from instrument",
    "Payable At": "Bank / Branch location",
    "Delivery Address": "Mailing / physical office address"
  }
- If no physical submissions are required in the text, output strictly: ["None specified in the provided text."]

5. Key Commercial Terms & Conditions to Follow
Extract strict operational, pricing, or compliance rules the bidder must adhere to from the ATC text. Include minor procedural instructions as well (e.g. required envelope superscription, required fields in a payment portal's remarks section, specific codes to be used) — these can cause bid rejection if missed and must not be summarized away.
Format each item as:
- "Topic (e.g. GST / Option Clause / Scope of Supply): Clear, concise explanation of the rule, penalty, or requirement"
"""

MAP_SYSTEM_PROMPT = """You are extracting raw evidence sentences from ONE OR MORE PAGES of a larger government tender ATC document. Do NOT summarize, interpret, categorize with judgment, or infer anything — copy exact sentences/clauses verbatim (or near-verbatim if a sentence is broken across a page boundary) into the correct bucket. If a bucket has nothing relevant in these pages, its list must be empty.

Reference — "Document required from seller" list (top section), for spotting which placeholders/documents/exemptions are being discussed. Do NOT re-output this list, it is context only:
{table_result}

Buckets:
1. STANDARD_DOCS — sentences naming/describing standard required documents (not "(Requested in ATC)" placeholders).
2. ATC_PLACEHOLDER_CLARIFICATION — sentences defining what a "(Requested in ATC)" placeholder actually is, OR mentioning any other mandatory certificate/registration/declaration/digital upload.
3. EXEMPTION — sentences about exemption eligibility (MSE, Startup, etc.) and/or the document required to claim an exemption.
4. PHYSICAL_SUBMISSION — sentences about EMD/PBG/hard copy/physical delivery, payee, payable-at bank, delivery address, deadlines for physical submission.
5. COMMERCIAL_TERMS — sentences describing operational/pricing/compliance rules, penalties, envelope superscription, portal remarks fields, specific codes, etc.

Output STRICTLY as minified JSON, no markdown fences, no commentary, with exactly these keys:
{{"STANDARD_DOCS": [], "ATC_PLACEHOLDER_CLARIFICATION": [], "EXEMPTION": [], "PHYSICAL_SUBMISSION": [], "COMMERCIAL_TERMS": []}}
Each value is a list of extracted sentence strings. Use an empty list if nothing on these pages belongs in that bucket."""

COMPRESS_SYSTEM_PROMPT = """You are merging duplicate/overlapping evidence sentences that were extracted from different pages of the same tender document, for a single category: {category}.
Remove exact or near-exact duplicates (e.g. repeated boilerplate/headers). Keep every distinct fact, deadline, name, amount, or condition. Do not summarize away specifics or invent anything not present in the input. Output ONE sentence per line, plain text, no numbering, no commentary."""

# =========================================================================
# DOCUMENT EXTRACTION
# =========================================================================
def extract_required_docs_from_json(json_filepath: str) -> str:
    """Extract required documents list from tender JSON structure."""
    if not os.path.exists(json_filepath):
        return f"Document required from seller:\nError: JSON file '{json_filepath}' not found."

    try:
        with open(json_filepath, "r", encoding="utf-8") as jf:
            data = json.load(jf)

        # Check in pdf -> documents -> required_from_seller
        docs = data.get("pdf", {}).get("documents", {}).get("required_from_seller", [])
        if not docs:
            # Fallback checks in case structure varies
            docs = data.get("documents", {}).get("required_from_seller", [])

        if isinstance(docs, list) and docs:
            items_str = "\n".join([f"- {d.strip()}" for d in docs if str(d).strip()])
            return f"Document required from seller:\n{items_str}"
        elif isinstance(docs, str) and docs.strip():
            return f"Document required from seller:\n{docs.strip()}"
        else:
            return "Document required from seller:\nNone specified"
    except Exception as e:
        return f"Document required from seller:\nError reading JSON: {e}"


def extract_atc_from_tender_pdf(pdf_filepath: str, start_marker: str, end_marker: str) -> str:
    """Extract ATC text between start_marker and end_marker using PyMuPDF from digital tender PDF."""
    if not os.path.exists(pdf_filepath):
        return f"Error: Tender PDF '{pdf_filepath}' not found."

    try:
        doc = pymupdf.open(pdf_filepath)
        page_texts = []
        for page_num in range(len(doc)):
            page_text = doc[page_num].get_text("text")
            page_texts.append(page_text)
        doc.close()

        full_text = "\n".join(page_texts)

        # Build regex patterns with \s+ so line breaks and spaces between words match cleanly
        start_pattern = r"\s+".join(re.escape(w) for w in start_marker.split())
        start_match = re.search(start_pattern, full_text, flags=re.IGNORECASE)
        if not start_match:
            return f"Error: Start marker '{start_marker}' not found in tender PDF."

        content_start_idx = start_match.end()
        end_pattern = r"\s+".join(re.escape(w) for w in end_marker.split())
        end_match = re.search(end_pattern, full_text[content_start_idx:], flags=re.IGNORECASE)

        if not end_match:
            # If end marker not found, take until end of text
            extracted = full_text[content_start_idx:].strip()
        else:
            extracted = full_text[content_start_idx:content_start_idx + end_match.start()].strip()

        return extracted
    except Exception as e:
        return f"Error extracting ATC from PDF '{pdf_filepath}': {e}"


def download_external_doc_bytes(url: str):
    """
    Download external document and detect whether it is a PDF or DOCX file.
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, timeout=30, headers=headers)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "").lower()
        url_lower = url.lower()
        
        is_pdf = "pdf" in content_type or ".pdf" in url_lower or resp.content.startswith(b"%PDF-")
        is_docx = (
            "wordprocessingml.document" in content_type
            or ".docx" in url_lower
            or (resp.content.startswith(b"PK\x03\x04") and ".docx" in url_lower)
        )

        if is_docx:
            return resp.content, "docx"
        elif is_pdf:
            return resp.content, "pdf"
        else:
            print(f"    [-] format not supported skipping it: '{content_type}' -> {url}")
            return None, None

    except Exception as e:
        print(f"    [-] Failed to download ATC document: {e}")
        return None, None


# Backwards compatibility alias
download_pdf_bytes = download_external_doc_bytes


def extract_pdf_pages_in_memory(pdf_bytes: bytes, base_name: str):
    """
    Extract text chunks from PDF in memory:
    - Digital pages: Extracted fast and accurately using PyMuPDF.
    - Non-digital / scanned pages: Processed through Mistral OCR manager using 'mistral-ocr-3-0'
      and converted to Markdown.
    """
    chunks = []
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)
    digital_page_texts = {}
    non_digital_page_indices = []

    for page_idx in range(total_pages):
        page = doc.load_page(page_idx)
        page_text = page.get_text("text").strip()
        # A page is digital if it has extractable text
        if page_text:
            digital_page_texts[page_idx] = page_text
        else:
            non_digital_page_indices.append(page_idx)
    doc.close()

    # Collect all pages into an ordered list: [(page_num, page_text)]
    page_items = []
    for page_idx, page_text in digital_page_texts.items():
        page_items.append((page_idx + 1, page_text))

    # 2. Process non-digital / scanned pages through Mistral OCR Manager (mistral-ocr-3-0)
    if non_digital_page_indices:
        print(f"    [*] Found {len(non_digital_page_indices)} non-digital page(s): {[p + 1 for p in non_digital_page_indices]}. Creating non-digital PDF for Mistral OCR (mistral-ocr-3-0)...")
        temp_pdf_path = None
        try:
            # Build a new PDF containing ONLY the non-digital pages
            src_doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            non_digital_doc = pymupdf.open()
            for p_idx in non_digital_page_indices:
                non_digital_doc.insert_pdf(src_doc, from_page=p_idx, to_page=p_idx)
            src_doc.close()

            fd, temp_pdf_path = tempfile.mkstemp(suffix=".pdf")
            os.close(fd)
            non_digital_doc.save(temp_pdf_path)
            non_digital_doc.close()

            # mistral_ocr_manager handles OCR and returns the markdown string
            ocr_markdown = process_pdf_to_markdown(
                file_path=temp_pdf_path,
                model="mistral-ocr-3-0"
            )

            if ocr_markdown and ocr_markdown.strip():
                # Split pages if multiple non-digital pages were processed
                ocr_pages = ocr_markdown.split("\n\n---\n\n")
                if len(ocr_pages) == len(non_digital_page_indices):
                    for idx, orig_p_idx in enumerate(non_digital_page_indices):
                        p_num = orig_p_idx + 1
                        page_md = ocr_pages[idx].strip()
                        if page_md:
                            page_items.append((p_num, page_md))
                            print(f"    [+] Mistral OCR page {p_num} completed ({len(page_md)} chars)")
                else:
                    # If page split didn't match exactly, attach whole markdown to first non-digital page
                    first_p_num = non_digital_page_indices[0] + 1
                    page_items.append((first_p_num, ocr_markdown.strip()))
                    print(f"    [+] Mistral OCR completed for non-digital pages ({len(ocr_markdown)} chars)")
        except Exception as ocr_err:
            print(f"    [-] Mistral OCR failed for non-digital pages: {ocr_err}")
        finally:
            if temp_pdf_path and os.path.exists(temp_pdf_path):
                try:
                    os.unlink(temp_pdf_path)
                except OSError:
                    pass

    # Sort all pages in strict ascending document page order (1, 2, 3...)
    page_items.sort(key=lambda item: item[0])
    if not page_items:
        return []

    # Dynamic token-budget chunking at page boundaries:
    # Pack consecutive pages into a single chunk. Only create a new chunk if adding the next page
    # would exceed the allowed token budget (CHUNK_CATEGORIZING_MAX_INPUT_TOKENS, default 1,000,000).
    max_chunk_tokens = CHUNK_CATEGORIZING_MAX_INPUT_TOKENS
    chunks = []
    current_pages = []
    current_tokens = 0
    current_start_p = page_items[0][0]

    for p_num, p_text in page_items:
        page_block = f"--- [Page {p_num}] ---\n{p_text}\n"
        page_tokens = count_tokens(page_block)

        # If adding this page exceeds limit (and current chunk is not empty), finish current chunk
        if current_tokens + page_tokens > max_chunk_tokens and current_pages:
            end_p = current_pages[-1][0]
            label = f"{base_name}_ATC_PDF_PAGES_{current_start_p}_TO_{end_p}" if current_start_p != end_p else f"{base_name}_ATC_PDF_PAGE_{current_start_p}"
            combined_text = "\n\n".join(txt for _, txt in current_pages).strip()
            chunks.append((label, combined_text))
            print(f"    [+] Created chunk '{label}': pages {current_start_p}-{end_p} ({current_tokens} tokens)")

            # Start new chunk with current page
            current_pages = [(p_num, page_block)]
            current_tokens = page_tokens
            current_start_p = p_num
        else:
            current_pages.append((p_num, page_block))
            current_tokens += page_tokens

    # Flush final chunk
    if current_pages:
        end_p = current_pages[-1][0]
        label = f"{base_name}_ATC_PDF_PAGES_{current_start_p}_TO_{end_p}" if current_start_p != end_p else f"{base_name}_ATC_PDF_PAGE_{current_start_p}"
        combined_text = "\n\n".join(txt for _, txt in current_pages).strip()
        chunks.append((label, combined_text))
        print(f"    [+] Created chunk '{label}': pages {current_start_p}-{end_p} ({current_tokens} tokens)")

    return chunks




def extract_docx_in_memory(docx_bytes: bytes, base_name: str):
    """
    Extract text chunks from DOCX in memory using python-docx.
    Extracts paragraphs and table contents.
    """
    chunks = []
    try:
        doc = docx.Document(io.BytesIO(docx_bytes))
        extracted_elements = []

        # Extract text from paragraphs
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                extracted_elements.append(text)

        # Extract text from tables
        for table in doc.tables:
            for row in table.rows:
                row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                # Deduplicate identical adjacent merged cells if any
                deduped = []
                for cell_text in row_cells:
                    if not deduped or deduped[-1] != cell_text:
                        deduped.append(cell_text)
                if deduped:
                    extracted_elements.append(" | ".join(deduped))

        full_docx_text = "\n\n".join(extracted_elements).strip()
        if full_docx_text:
            chunks.append((f"{base_name}_ATC_DOCX_CHUNK_1", full_docx_text))
            print(f"    [+] Successfully extracted text from DOCX ({len(full_docx_text)} chars)")
        else:
            print(f"    [-] Warning: DOCX document '{base_name}' contained no extractable text.")
    except Exception as e:
        print(f"    [-] Error extracting text from DOCX using python-docx: {e}")
        raise e
    return chunks


def extract_document_chunks_in_memory(input_path: str):
    """
    Extract required documents from JSON and ATC text chunks from digital tender PDF
    and downloaded ATC document (PDF via PyMuPDF or DOCX via python-docx).
    """
    dir_path = os.path.dirname(input_path) if os.path.isfile(input_path) else input_path
    base_name = os.path.splitext(os.path.basename(input_path))[0]

    # Resolve JSON and PDF filepaths
    json_filepath = os.path.join(dir_path, f"{base_name}.json")
    if not os.path.exists(json_filepath):
        # In case input_path itself is the json file
        if input_path.endswith(".json"):
            json_filepath = input_path

    pdf_filepath = os.path.join(dir_path, f"{base_name}.pdf")

    # 1. Extract Document Required from Seller from JSON
    table_result = extract_required_docs_from_json(json_filepath)

    atc_parts = []

    # 2. Extract ATC from digital tender PDF using PyMuPDF
    if os.path.exists(pdf_filepath):
        pdf_chunk_result = extract_atc_from_tender_pdf(pdf_filepath, ATC_SECTION_START_MARKER, ATC_SECTION_END_MARKER)
        if pdf_chunk_result and not pdf_chunk_result.startswith("Error:"):
            # Clean up buyer uploaded link line if present in text
            pdf_chunk_result = re.sub(
                r"Buyer uploaded ATC document\s*\[?Click here to view the file\]?\([^)]*\)?",
                "", pdf_chunk_result, flags=re.IGNORECASE,
            )
            pdf_chunk_result = pdf_chunk_result.replace(
                "Buyer uploaded ATC document Click here to view the file", ""
            ).strip()

            if pdf_chunk_result:
                atc_parts.append(("Main Bid ATC", pdf_chunk_result))
        else:
            print(f"    [-] Tender PDF ATC extraction warning: {pdf_chunk_result}")
    else:
        print(f"    [-] Tender PDF not found: {pdf_filepath}")

    # 3. Check JSON hyperlinks for Buyer uploaded ATC document and download it
    downloaded_bytes = None
    file_type = None

    if os.path.exists(json_filepath):
        try:
            with open(json_filepath, "r", encoding="utf-8") as jf:
                data = json.load(jf)
            for link in data.get("hyperlinks", []):
                name = link.get("name", "")
                url = link.get("url")
                if ATC_PDF_LINK_NAME.lower() in name.lower() and url:
                    print(f"    [+] Found ATC hyperlink: '{name}' -> {url}")
                    downloaded_bytes, file_type = download_external_doc_bytes(url)
                    break
        except Exception as e:
            print(f"    [-] Error parsing JSON in {json_filepath}: {e}")

    downloaded_chunks = []
    if downloaded_bytes:
        if file_type == "pdf":
            try:
                downloaded_chunks = extract_pdf_pages_in_memory(downloaded_bytes, base_name)
            except Exception as e:
                print(f"    [-] {e}")
        elif file_type == "docx":
            try:
                downloaded_chunks = extract_docx_in_memory(downloaded_bytes, base_name)
            except Exception as e:
                print(f"    [-] DOCX extraction failed: {e}")

    # Merge Main Tender ATC + Downloaded Buyer ATC into ONE final unified document
    all_content_parts = []
    if atc_parts:
        all_content_parts.append(f"=== [MAIN BID ATC CLAUSES] ===\n{atc_parts[0][1]}")

    if downloaded_chunks:
        # If downloaded document was multi-chunked (e.g. exceeded 1M tokens), join their text
        downloaded_combined = "\n\n".join(txt for _, txt in downloaded_chunks)
        all_content_parts.append(f"=== [BUYER UPLOADED ATC DOCUMENT] ===\n{downloaded_combined}")

    final_unified_text = "\n\n".join(all_content_parts).strip()

    chunks = []
    if final_unified_text:
        # Check if total unified text fits within Gemini's 1M token budget
        total_tokens = count_tokens(final_unified_text)
        if total_tokens <= CHUNK_CATEGORIZING_MAX_INPUT_TOKENS:
            chunks.append((f"{base_name}_FINAL_UNIFIED_ATC", final_unified_text))
        else:
            # Only split if total exceeds the 1,000,000 token limit
            if atc_parts:
                chunks.append((f"{base_name}_MAIN_BID_ATC", atc_parts[0][1]))
            chunks.extend(downloaded_chunks)
    else:
        chunks.append((f"{base_name}_ATC_CHUNK_1", "No Valid ATC Found"))

    if not chunks:
        chunks.append((f"{base_name}_ATC_CHUNK_1", "No Valid ATC Found"))

    return table_result, chunks


# =========================================================================
# MAP STAGE
# =========================================================================
def map_extract_chunk(table_result: str, chunk_label: str, atc_text: str, strict: bool = False) -> dict:
    categories = (
        "STANDARD_DOCS",
        "ATC_PLACEHOLDER_CLARIFICATION",
        "EXEMPTION",
        "PHYSICAL_SUBMISSION",
        "COMMERCIAL_TERMS",
    )
    empty = {c: [] for c in categories}
    system_prompt = MAP_SYSTEM_PROMPT.format(table_result=table_result)
    
    budget_check = count_tokens(system_prompt) + count_tokens(atc_text)
    if budget_check > CHUNK_CATEGORIZING_MAX_INPUT_TOKENS:
        allowed_chars = int(len(atc_text) * (CHUNK_CATEGORIZING_MAX_INPUT_TOKENS / budget_check) * 0.95)
        atc_text = atc_text[:allowed_chars]

    raw = timed_gemini_call(
        f"Processing {chunk_label} (MAP stage)",
        f"MAP: {chunk_label}",
        system_prompt,
        atc_text,
        max_tokens=CHUNK_CATEGORIZING_MAX_OUTPUT_TOKENS,
        require_json=True
    )
    
    if not raw:
        if strict: 
            raise ValueError("Empty response")
        return empty

    raw_clean = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(raw_clean)
        result = {}
        for c in categories:
            v = parsed.get(c, [])
            result[c] = v if isinstance(v, list) else [str(v)]
        return result
    except Exception:
        if strict:
            raise ValueError("Invalid JSON format from model")
            
        print(f"    [!] {chunk_label}: map-stage output wasn't valid JSON, preserving raw text fallback")
        fallback = empty
        fallback["COMMERCIAL_TERMS"] = [f"[UNPARSED EVIDENCE - {chunk_label}] {raw_clean[:1500]}"]
        return fallback


def dedupe_preserve_order(items):
    seen = set()
    out = []
    for it in items:
        key = re.sub(r"\s+", " ", it.strip().lower())
        if key and key not in seen:
            seen.add(key)
            out.append(it.strip())
    return out


def strip_stray_hr_lines(text: str) -> str:
    if not text:
        return text
    lines = [ln for ln in text.splitlines() if not re.fullmatch(r"\s*(-{3,}|\*{3,}|_{3,})\s*", ln)]
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


# =========================================================================
# REDUCE & COMPRESSION STAGE
# =========================================================================
def compress_category(category: str, lines: list) -> list:
    joined = "\n".join(lines)
    system_prompt = COMPRESS_SYSTEM_PROMPT.format(category=category)
    out = timed_gemini_call(
        f"Compressing category '{category}'",
        f"COMPRESS: {category}",
        system_prompt,
        joined,
        max_tokens=CHUNK_CATEGORIZING_MAX_OUTPUT_TOKENS
    )
    if not out:
        return lines
    return [l.strip("- ").strip() for l in out.splitlines() if l.strip()]


def build_reduced_evidence_text(merged: dict) -> str:
    categories = (
        "STANDARD_DOCS",
        "ATC_PLACEHOLDER_CLARIFICATION",
        "EXEMPTION",
        "PHYSICAL_SUBMISSION",
        "COMMERCIAL_TERMS",
    )
    parts = []
    for c in categories:
        lines = merged.get(c, [])
        parts.append(f"[{c}]")
        if lines:
            parts.extend(f"- {l}" for l in lines)
        else:
            parts.append("- (none found)")
        parts.append("")
    return "\n".join(parts).strip()


def reduce_stage(table_result: str, merged: dict) -> str:
    categories = (
        "STANDARD_DOCS",
        "ATC_PLACEHOLDER_CLARIFICATION",
        "EXEMPTION",
        "PHYSICAL_SUBMISSION",
        "COMMERCIAL_TERMS",
    )
    evidence_text = build_reduced_evidence_text(merged)
    budget_check = count_tokens(ANALYSIS_SYSTEM_PROMPT) + count_tokens(table_result) + count_tokens(evidence_text)

    attempts = 0
    while budget_check > FINAL_STAGE_INPUT_TOKENS and attempts < 3:
        attempts += 1
        biggest_cat = max(categories, key=lambda c: sum(len(l) for l in merged.get(c, [])))
        if not merged.get(biggest_cat):
            break
        print(f"    [!] Evidence oversized ({budget_check} tokens), compressing category '{biggest_cat}' (pass {attempts})")
        merged[biggest_cat] = compress_category(biggest_cat, merged[biggest_cat])
        evidence_text = build_reduced_evidence_text(merged)
        budget_check = count_tokens(ANALYSIS_SYSTEM_PROMPT) + count_tokens(table_result) + count_tokens(evidence_text)

    user_prompt = (
        f"Document required from seller:\n{table_result}\n\n"
        f"======\n\n"
        f"Additional Terms and Conditions (compacted evidence extracted from all pages):\n{evidence_text}\n"
    )

    result = timed_gemini_call(
        f"Running Combining Stage - final analysis ({GEMINI_MODEL})",
        "Combining Stage",
        ANALYSIS_SYSTEM_PROMPT,
        user_prompt,
        max_tokens=FINAL_STAGE_OUTPUT_TOKENS,
        require_json=True
    )
    return result


def single_shot_stage(table_result: str, atc_text: str) -> str:
    user_prompt = (
        f"Document required from seller:\n{table_result}\n\n"
        f"======\n\n"
        f"Additional Terms and Conditions:\n{atc_text}\n"
    )
    result = timed_gemini_call(
        f"Running single-chunk analysis ({GEMINI_MODEL})",
        "SINGLE-SHOT",
        ANALYSIS_SYSTEM_PROMPT,
        user_prompt,
        max_tokens=FINAL_STAGE_OUTPUT_TOKENS,
        require_json=True
    )
    return result


# =========================================================================
# MAIN PIPELINE
# =========================================================================
def process_document(input_filepath: str, base_name: str):
    TOKEN_RECORDS.clear()

    timer = ProgressTimer(f"Generating chunks for {base_name}")
    timer.start()
    table_result, chunks = extract_document_chunks_in_memory(input_filepath)
    timer.stop()

    chunks = [(name, atc) for name, atc in chunks if atc]
    if not chunks:
        print(f"    [-] No usable chunk text found in {input_filepath}, skipping.")
        return

    # Save chunks to CHUNKS folder for inspection
    try:
        os.makedirs(CHUNKS_OUTPUT_DIR, exist_ok=True)
        bid_chunks_dir = os.path.join(CHUNKS_OUTPUT_DIR, base_name)
        os.makedirs(bid_chunks_dir, exist_ok=True)
        for chunk_name, chunk_text in chunks:
            safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', chunk_name)
            chunk_file_path = os.path.join(bid_chunks_dir, f"{safe_name}.txt")
            with open(chunk_file_path, "w", encoding="utf-8") as cf:
                cf.write(chunk_text)
        print(f"    [📁] Saved {len(chunks)} chunk(s) to folder: {bid_chunks_dir}")
    except Exception as e:
        print(f"    [!] Warning: Failed to save chunks to disk: {e}")

    if len(chunks) == 1:
        print(f"    -> Single chunk detected ({chunks[0][0]}): running one-shot analysis")
        final_answer = single_shot_stage(table_result, chunks[0][1])
    else:
        print(f"    -> {len(chunks)} chunks detected. Running MAP-REDUCE chunking pipeline via Gemini...")
        reduce_categories = (
            "STANDARD_DOCS",
            "ATC_PLACEHOLDER_CLARIFICATION",
            "EXEMPTION",
            "PHYSICAL_SUBMISSION",
            "COMMERCIAL_TERMS",
        )
        merged = {c: [] for c in reduce_categories}

        # 1. Process original tender document ATC chunk (from digital tender PDF) standalone first
        main_chunk = next((c for c in chunks if "ATC_PDF_MAIN_CHUNK" in c[0]), None)
        downloaded_chunks = [c for c in chunks if c != main_chunk]

        if main_chunk:
            print(f"    -> Processing standalone tender ATC: {main_chunk[0]}")
            main_result = map_extract_chunk(table_result, main_chunk[0], main_chunk[1], strict=False)
            for c in reduce_categories:
                merged[c].extend(main_result.get(c, []))

        # 2. Dynamic Self-Healing Batch Queue for external downloaded pages (PDF)
        if downloaded_chunks:
            base_prompt_tokens = count_tokens(MAP_SYSTEM_PROMPT.format(table_result=table_result))
            pending_chunks = downloaded_chunks.copy()

            while pending_chunks:
                current_batch_names = []
                current_batch_texts = []
                current_tokens = base_prompt_tokens

                for name, atc_text in pending_chunks:
                    chunk_addition = f"\n\n--- [START {name}] ---\n{atc_text}\n--- [END {name}] ---\n"
                    chunk_tokens = count_tokens(chunk_addition)

                    if current_tokens + chunk_tokens > (CHUNK_CATEGORIZING_MAX_INPUT_TOKENS - 200) and current_batch_names:
                        break

                    current_batch_names.append(name)
                    current_batch_texts.append(chunk_addition)
                    current_tokens += chunk_tokens

                success = False
                while current_batch_names and not success:
                    batch_label = " + ".join(current_batch_names)
                    batch_text = "".join(current_batch_texts)

                    try:
                        page_result = map_extract_chunk(table_result, batch_label, batch_text, strict=True)
                        for c in reduce_categories:
                            merged[c].extend(page_result.get(c, []))
                        success = True
                        pending_chunks = pending_chunks[len(current_batch_names):]

                    except ValueError:
                        if len(current_batch_names) > 1:
                            print(f"    [!] JSON decode failed on batch. Halving batch to heal...")
                            current_batch_names.pop()
                            current_batch_texts.pop()
                        else:
                            print(f"    [!] Single chunk '{batch_label}' JSON parse failed. Retrying in fallback mode.")
                            page_result = map_extract_chunk(table_result, batch_label, batch_text, strict=False)
                            for c in reduce_categories:
                                merged[c].extend(page_result.get(c, []))
                            success = True
                            pending_chunks = pending_chunks[1:]

        # Deduplicate sentences across all processed chunks
        for c in reduce_categories:
            merged[c] = dedupe_preserve_order(merged[c])

        print(f"    -> Running Combining Stage (Reduce & Synthesis)")
        final_answer = reduce_stage(table_result, merged)

    if not final_answer:
        print(f"    [-] Analysis failed for {base_name} (empty model response).")
        print_token_table(TOKEN_RECORDS, base_name)
        return

    # Clean and parse JSON response
    cleaned_json_text = re.sub(r"^```(json)?|```$", "", final_answer.strip(), flags=re.MULTILINE).strip()
    try:
        parsed_json = json.loads(cleaned_json_text)
        final_json_str = json.dumps(parsed_json, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"    [!] Warning: Could not parse output as JSON ({e}), saving raw text")
        final_json_str = cleaned_json_text

    os.makedirs(ANALYSIS_OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(ANALYSIS_OUTPUT_DIR, f"{base_name}_INFER_OUTPUT.json")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(final_json_str)

    print(f"    [✓] Saved: {out_path}")
    print_token_table(TOKEN_RECORDS, base_name)


def main():
    multiprocessing.freeze_support()

    if len(sys.argv) < 2:
        print("Usage: python INFERENCE_ON_MARKDOWN.py <path_to_tender_directory>")
        sys.exit(1)

    root = sys.argv[1]
    if not os.path.isdir(root):
        print(f"'{root}' not found (expected a folder of tender folders/files).")
        return

    # Find unique document base paths (looking for .json or .pdf)
    tender_targets = {}
    for r, _dirs, files in os.walk(root):
        for f in files:
            if f.endswith(".json") and not f.endswith("_ocr.json"):
                base = os.path.splitext(f)[0]
                tender_targets[base] = os.path.join(r, f)
            elif f.endswith(".pdf") and not f.endswith("_RA.pdf"):
                base = os.path.splitext(f)[0]
                if base not in tender_targets:
                    tender_targets[base] = os.path.join(r, f)

    if not tender_targets:
        print(f"No tender JSON or PDF files found under '{root}'.")
        return

    sorted_keys = sorted(tender_targets.keys())
    print(f"Found {len(sorted_keys)} document(s). Starting MAP-REDUCE extraction via Gemini...\n")
    print("=" * 65)

    for base_name in sorted_keys:
        filepath = tender_targets[base_name]
        print(f"\n📂 Analyzing: {base_name}")
        try:
            process_document(filepath, base_name)
        except Exception as e:
            print(f"    [-] Unexpected error on {base_name}: {e}")
        print("-" * 65)

    print(f"\n🎉 SUCCESS: All documents analyzed.")
    print(f"⏱  Total inference time across all documents/stages: {GRAND_TOTAL_SECONDS:.2f}s")


if __name__ == "__main__":
    main()