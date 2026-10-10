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
  - Multi-LLM provider execution (Gemini API, OpenAI Chat Completions API)
  - PyMuPDF in-memory parsing for digital pages
  - Multi-OCR provider fallback for non-digital/scanned pages (Mistral, Gemini, OpenAI via DocumentOCRFactory)
  - Dedicated workspace temp_storage for transient OCR sub-PDFs
  - External DOCX extraction using python-docx
  - Local Vertex AI tokenizer for offline token budgeting and cost calculation
  - Page-boundary token budgeting: single-shot execution up to 1,000,000 tokens,
    dynamic Map-Reduce when exceeding budget
  - Automatic persistence of <bid_no>_ATC.md and downloaded external files in the bid directory
"""

import base64
import io
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import docx
from openai import OpenAI
import pymupdf
import requests
import tiktoken
from vertexai.preview import tokenization

from config.settings import (
    ATC_LLM_PROVIDER,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_OCR_MODEL,
    MISTRAL_OCR_MODEL,
    OCR_PROVIDER,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_OCR_MODEL,
    USD_TO_INR_RATE,
)
from core.mistral_ocr_manager import (
    get_mistral_client,
    ocr_json_to_markdown,
    ocr_response_to_dict,
)
from core.ocr.gemini_provider import GEMINI_OCR_SYSTEM_PROMPT
from core.ocr.openai_provider import OPENAI_OCR_PROMPT
from core.ocr.pricing import PRICING_CATALOG
from utils.logger import get_logger

log = get_logger("atc_analyzer")

# ---------------------------------------------------------------------------
# PATH CONFIGURATION
# ---------------------------------------------------------------------------
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# TOKEN BUDGETING & MODEL LIMITS
# ---------------------------------------------------------------------------
CHUNK_CATEGORIZING_MAX_INPUT_TOKENS = 1000000
CHUNK_CATEGORIZING_MAX_OUTPUT_TOKENS = 65536
FINAL_STAGE_INPUT_TOKENS = 1000000
FINAL_STAGE_OUTPUT_TOKENS = 65536

# Local Vertex AI Tokenizer for Gemini models
_tokenizer_model_id = "gemini-1.5-flash-002" if "flash" in (GEMINI_MODEL or "").lower() else "gemini-1.5-pro-002"
_gemini_tokenizer = tokenization.get_tokenizer_for_model(_tokenizer_model_id)

# Local tiktoken tokenizer for OpenAI models (gpt-4o tokenizer covers gpt-4o, gpt-4o-mini and higher models)
_openai_tokenizer = tiktoken.encoding_for_model("gpt-4o")


def count_tokens(text: str) -> int:
    """
    Return precise offline token count matching the active ATC_LLM_PROVIDER:
    - If openai: Uses tiktoken.encoding_for_model.
    - If gemini: Uses local Vertex AI tokenizer.
    """
    if not text:
        return 0

    provider = (ATC_LLM_PROVIDER or "gemini").lower()
    if provider == "openai":
        return len(_openai_tokenizer.encode(text))
    return _gemini_tokenizer.count_tokens(text).total_tokens


# ---------------------------------------------------------------------------
# MARKERS
# ---------------------------------------------------------------------------
ATC_SECTION_START_MARKER = "Buyer Added Bid Specific Terms and Conditions"
ATC_SECTION_END_MARKER = "Disclaimer"
ATC_PDF_LINK_NAME = "Buyer uploaded ATC document"


# ---------------------------------------------------------------------------
# PROMPT DEFINITIONS
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# EXTRACTION HELPERS
# ---------------------------------------------------------------------------
def extract_required_docs_text(parsed_pdf_data: Optional[Dict[str, Any]] = None) -> str:
    """Extract 'Document required from seller' strictly from in-memory parsed_pdf_data."""
    if parsed_pdf_data and isinstance(parsed_pdf_data, dict):
        docs = (
            parsed_pdf_data.get("documents", {}).get("required_from_seller", [])
            or parsed_pdf_data.get("pdf", {}).get("documents", {}).get("required_from_seller", [])
        )
        if isinstance(docs, list) and docs:
            items_str = ", ".join([str(d).strip() for d in docs if str(d).strip()])
            return f"Document required from seller : {items_str}"
        elif isinstance(docs, str) and docs.strip():
            return f"Document required from seller : {docs.strip()}"

    return "Document required from seller : None specified in main document"


def extract_embedded_atc_text(markdown_text: str) -> str:
    """Extract embedded ATC text between start and end markers (case-insensitive & whitespace-flexible)."""
    if not markdown_text:
        return ""

    start_pattern = r"\s+".join(re.escape(w) for w in ATC_SECTION_START_MARKER.split())
    start_m = re.search(start_pattern, markdown_text, flags=re.IGNORECASE)
    if not start_m:
        return ""

    content_start_idx = start_m.end()

    end_pattern = r"\s+".join(re.escape(w) for w in ATC_SECTION_END_MARKER.split())
    end_m = re.search(end_pattern, markdown_text[content_start_idx:], flags=re.IGNORECASE)

    if end_m:
        extracted = markdown_text[content_start_idx:content_start_idx + end_m.start()].strip()
    else:
        extracted = markdown_text[content_start_idx:content_start_idx + 35000].strip()

    # Clean out boilerplate hyperlink text
    extracted = re.sub(
        r"Buyer uploaded ATC document\s*\[?Click here to view the file\]?\([^)]*\)?",
        "", extracted, flags=re.IGNORECASE
    )
    extracted = extracted.replace("Buyer uploaded ATC document Click here to view the file", "").strip()

    return extracted


# ---------------------------------------------------------------------------
# EXTERNAL DOCUMENT DOWNLOAD & EXTRACTION (DOCX / HYBRID PDF)
# ---------------------------------------------------------------------------
def download_external_doc_bytes(url: str, safe_bid_no: str, save_dir: Optional[str] = None) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Download external document and detect whether it is a PDF or DOCX file.
    If save_dir is specified, persists the file inside the bid folder.
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

        file_type = None
        if is_docx:
            file_type = "docx"
        elif is_pdf:
            file_type = "pdf"
        else:
            log.warning(f"Unsupported external document format '{content_type}' at {url}")
            return None, None

        # Save downloaded external document into the bid directory
        if save_dir and os.path.exists(save_dir):
            target_ext = "docx" if file_type == "docx" else "pdf"
            saved_file_name = f"{safe_bid_no}_ATC_{target_ext.upper()}.{target_ext}"
            saved_file_path = os.path.join(save_dir, saved_file_name)
            try:
                with open(saved_file_path, "wb") as f:
                    f.write(resp.content)
                log.info(f"Saved downloaded external ATC document to {saved_file_path}")
            except Exception as e:
                log.warning(f"Could not persist external document to {saved_file_path}: {e}")

        return resp.content, file_type

    except Exception as e:
        log.warning(f"Failed to download ATC document from {url}: {e}")
        return None, None


def extract_docx_in_memory(docx_bytes: bytes, base_name: str) -> List[Tuple[str, str]]:
    """Extract text from DOCX in memory using python-docx."""
    try:
        doc = docx.Document(io.BytesIO(docx_bytes))
        extracted_elements = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                extracted_elements.append(text)

        for table in doc.tables:
            for row in table.rows:
                row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                deduped = []
                for cell_text in row_cells:
                    if not deduped or deduped[-1] != cell_text:
                        deduped.append(cell_text)
                if deduped:
                    extracted_elements.append(" | ".join(deduped))

        full_docx_text = "\n\n".join(extracted_elements).strip()
        if full_docx_text:
            log.info(f"Successfully extracted text from DOCX ({len(full_docx_text)} chars)")
            return [(f"{base_name}_ATC_DOCX_CHUNK_1", full_docx_text)]
        return []
    except Exception as e:
        log.error(f"Error extracting text from DOCX: {e}")
        return []


def process_non_digital_sub_pdf_bytes_ocr(sub_pdf_bytes: bytes, provider_name: str) -> str:
    """
    Dispatch non-digital sub-PDF bytes directly to OCR provider in-memory without saving to disk.
    Supports mistral, gemini, and openai.
    """
    effective_provider = (provider_name or "mistral").lower()
    try:
        b64_pdf = base64.b64encode(sub_pdf_bytes).decode("utf-8")

        if effective_provider == "mistral":
            client = get_mistral_client()
            process_kwargs = {
                "document": {
                    "type": "document_url",
                    "document_url": f"data:application/pdf;base64,{b64_pdf}",
                },
                "model": MISTRAL_OCR_MODEL,
                "include_image_base64": False,
                "table_format": "html",
                "extract_header": True,
                "extract_footer": True,
            }
            ocr_response = client.ocr.process(**process_kwargs)
            data = ocr_response_to_dict(ocr_response)
            return ocr_json_to_markdown(data)

        elif effective_provider == "gemini":
            model_name = GEMINI_OCR_MODEL or "gemini-2.5-flash"
            api_key = GEMINI_API_KEY
            if not api_key:
                raise ValueError("GEMINI_API_KEY not set")
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"inline_data": {"mime_type": "application/pdf", "data": b64_pdf}},
                            {"text": GEMINI_OCR_SYSTEM_PROMPT}
                        ]
                    }
                ],
                "generationConfig": {"temperature": 0.0}
            }
            resp = requests.post(endpoint, json=payload, timeout=120)
            if resp.status_code == 200:
                candidates = resp.json().get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    return "".join(p.get("text", "") for p in parts).strip()
            return ""

        elif effective_provider == "openai":
            client = OpenAI(api_key=OPENAI_API_KEY)
            doc = pymupdf.open(stream=sub_pdf_bytes, filetype="pdf")
            content_parts = [{"type": "text", "text": OPENAI_OCR_PROMPT}]
            for p_idx in range(len(doc)):
                pix = doc[p_idx].get_pixmap(dpi=150)
                img_b64 = base64.b64encode(pix.tobytes("jpeg")).decode("utf-8")
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}", "detail": "high"}
                })
            doc.close()
            response = client.chat.completions.create(
                model=OPENAI_OCR_MODEL or "gpt-4o-mini",
                messages=[{"role": "user", "content": content_parts}],
                temperature=0.0
            )
            return response.choices[0].message.content or ""

    except Exception as e:
        log.error(f"In-memory OCR failed using provider '{effective_provider}': {e}")
        return ""

    return ""


def extract_pdf_pages_in_memory(pdf_bytes: bytes, base_name: str) -> List[Tuple[str, str]]:
    """
    Inspect PDF page-by-page entirely in-memory:
    - Digital pages: PyMuPDF.
    - Non-digital / scanned pages: In-memory sub-PDF bytes sent directly to configured OCR_PROVIDER.
    - Interleaved in exact document page order.
    - Packed into chunks bounded by the token budget.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)
    digital_page_texts = {}
    non_digital_page_indices = []

    for page_idx in range(total_pages):
        page = doc.load_page(page_idx)
        page_text = page.get_text("text").strip()
        if page_text:
            digital_page_texts[page_idx] = page_text
        else:
            non_digital_page_indices.append(page_idx)
    doc.close()

    page_items = []
    for page_idx, page_text in digital_page_texts.items():
        page_items.append((page_idx + 1, page_text))

    # Process non-digital pages in-memory if any
    if non_digital_page_indices:
        log.info(f"Found {len(non_digital_page_indices)} non-digital page(s): {[p + 1 for p in non_digital_page_indices]}. Sending in-memory sub-PDF to OCR...")
        try:
            src_doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            non_digital_doc = pymupdf.open()
            for p_idx in non_digital_page_indices:
                non_digital_doc.insert_pdf(src_doc, from_page=p_idx, to_page=p_idx)
            src_doc.close()

            # Generate in-memory PDF bytes (never saved to disk)
            sub_pdf_bytes = non_digital_doc.tobytes(garbage=4, deflate=True)
            non_digital_doc.close()

            ocr_markdown = process_non_digital_sub_pdf_bytes_ocr(sub_pdf_bytes, OCR_PROVIDER)

            if ocr_markdown and ocr_markdown.strip():
                ocr_pages = ocr_markdown.split("\n\n---\n\n")
                if len(ocr_pages) == len(non_digital_page_indices):
                    for idx, orig_p_idx in enumerate(non_digital_page_indices):
                        p_num = orig_p_idx + 1
                        page_md = ocr_pages[idx].strip()
                        if page_md:
                            page_items.append((p_num, page_md))
                else:
                    first_p_num = non_digital_page_indices[0] + 1
                    page_items.append((first_p_num, ocr_markdown.strip()))
                log.info(f"In-memory OCR completed for {len(non_digital_page_indices)} page(s) ({len(ocr_markdown)} chars)")
        except Exception as ocr_err:
            log.error(f"In-memory OCR failed for non-digital pages: {ocr_err}")

    # Sort pages in document order
    page_items.sort(key=lambda item: item[0])
    if not page_items:
        return []

    # Pack into token-budgeted chunks
    max_chunk_tokens = CHUNK_CATEGORIZING_MAX_INPUT_TOKENS
    chunks = []
    current_pages = []
    current_tokens = 0
    current_start_p = page_items[0][0]

    for p_num, p_text in page_items:
        page_block = f"--- [Page {p_num}] ---\n{p_text}\n"
        page_tokens = count_tokens(page_block)

        if current_tokens + page_tokens > max_chunk_tokens and current_pages:
            end_p = current_pages[-1][0]
            label = f"{base_name}_ATC_PDF_PAGES_{current_start_p}_TO_{end_p}" if current_start_p != end_p else f"{base_name}_ATC_PDF_PAGE_{current_start_p}"
            combined_text = "\n\n".join(txt for _, txt in current_pages).strip()
            chunks.append((label, combined_text))

            current_pages = [(p_num, page_block)]
            current_tokens = page_tokens
            current_start_p = p_num
        else:
            current_pages.append((p_num, page_block))
            current_tokens += page_tokens

    if current_pages:
        end_p = current_pages[-1][0]
        label = f"{base_name}_ATC_PDF_PAGES_{current_start_p}_TO_{end_p}" if current_start_p != end_p else f"{base_name}_ATC_PDF_PAGE_{current_start_p}"
        combined_text = "\n\n".join(txt for _, txt in current_pages).strip()
        chunks.append((label, combined_text))

    return chunks


# ---------------------------------------------------------------------------
# LLM INFERENCE CLIENTS (GEMINI & OPENAI)
# ---------------------------------------------------------------------------
def call_gemini(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4000,
    temperature: float = 0.1,
    require_json: bool = False,
    retries: int = 3
) -> Tuple[str, int, int]:
    """Call Google Gemini API. Returns (output_text, input_tokens, output_tokens)."""
    if not GEMINI_API_KEY:
        log.error("GEMINI_API_KEY is not set.")
        return "", 0, 0

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
    }
    if system_prompt:
        payload["system_instruction"] = {"parts": [{"text": system_prompt}]}
    if require_json:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    headers = {"Content-Type": "application/json"}

    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=180)
            if resp.status_code == 200:
                data = resp.json()
                usage = data.get("usageMetadata", {})
                in_tok = usage.get("promptTokenCount") or count_tokens(system_prompt + user_prompt)
                out_tok = usage.get("candidatesTokenCount") or 0

                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        text_val = parts[0].get("text", "").strip()
                        if not out_tok:
                            out_tok = count_tokens(text_val)
                        return text_val, in_tok, out_tok
                return "", in_tok, out_tok
            elif resp.status_code == 429:
                wait_time = attempt * 5
                log.warning(f"Gemini API rate limited (429). Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                log.error(f"Gemini API error (HTTP {resp.status_code}): {resp.text[:300]}")
                if attempt < retries and resp.status_code >= 500:
                    time.sleep(attempt * 2)
                else:
                    return "", 0, 0
        except requests.exceptions.RequestException as e:
            log.warning(f"Gemini API connection error (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(attempt * 2)
            else:
                return "", 0, 0

    return "", 0, 0


def call_openai(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4000,
    temperature: float = 0.1,
    require_json: bool = False,
    retries: int = 3
) -> Tuple[str, int, int]:
    """Call OpenAI API. Returns (output_text, input_tokens, output_tokens)."""
    if not OPENAI_API_KEY:
        log.error("OPENAI_API_KEY is not set.")
        return "", 0, 0

    url = "https://api.openai.com/v1/chat/completions"
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if require_json:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }

    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=180)
            if resp.status_code == 200:
                data = resp.json()
                usage = data.get("usage", {})
                in_tok = usage.get("prompt_tokens", 0)
                out_tok = usage.get("completion_tokens", 0)
                choices = data.get("choices", [])
                if choices:
                    text_val = choices[0].get("message", {}).get("content", "").strip()
                    return text_val, in_tok, out_tok
                return "", in_tok, out_tok
            elif resp.status_code == 429:
                wait_time = attempt * 5
                log.warning(f"OpenAI API rate limited (429). Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                log.error(f"OpenAI API error (HTTP {resp.status_code}): {resp.text[:300]}")
                if attempt < retries and resp.status_code >= 500:
                    time.sleep(attempt * 2)
                else:
                    return "", 0, 0
        except requests.exceptions.RequestException as e:
            log.warning(f"OpenAI connection error (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(attempt * 2)
            else:
                return "", 0, 0

    return "", 0, 0


def call_atc_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4000,
    require_json: bool = False
) -> Tuple[str, int, int]:
    """Dispatch LLM request to configured ATC_LLM_PROVIDER (gemini | openai)."""
    provider = (ATC_LLM_PROVIDER or "gemini").lower()
    if provider == "openai":
        return call_openai(system_prompt, user_prompt, max_tokens=max_tokens, require_json=require_json)
    return call_gemini(system_prompt, user_prompt, max_tokens=max_tokens, require_json=require_json)


def calculate_llm_cost(provider: str, model_name: str, in_tokens: int, out_tokens: int) -> Tuple[float, float]:
    """Calculate USD and INR cost dynamically from PRICING_CATALOG."""
    catalog = PRICING_CATALOG.get(provider.lower(), {})
    model_pricing = catalog.get(model_name, {})
    in_rate = model_pricing.get("input_per_million", 0.0)
    out_rate = model_pricing.get("output_per_million", 0.0)

    usd = (in_tokens * in_rate / 1_000_000) + (out_tokens * out_rate / 1_000_000)
    inr = usd * USD_TO_INR_RATE
    return usd, inr


# ---------------------------------------------------------------------------
# MAP-REDUCE & SINGLE-SHOT STAGES
# ---------------------------------------------------------------------------
def map_extract_chunk(table_result: str, chunk_label: str, atc_text: str) -> Tuple[dict, int, int]:
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

    raw, in_tok, out_tok = call_atc_llm(
        system_prompt,
        atc_text,
        max_tokens=CHUNK_CATEGORIZING_MAX_OUTPUT_TOKENS,
        require_json=True
    )
    if not raw:
        return empty, in_tok, out_tok

    raw_clean = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(raw_clean)
        result = {}
        for c in categories:
            v = parsed.get(c, [])
            result[c] = v if isinstance(v, list) else [str(v)]
        return result, in_tok, out_tok
    except Exception:
        fallback = empty
        fallback["COMMERCIAL_TERMS"] = [f"[UNPARSED EVIDENCE - {chunk_label}] {raw_clean[:1500]}"]
        return fallback, in_tok, out_tok


def dedupe_preserve_order(items: list) -> list:
    seen = set()
    out = []
    for it in items:
        key = re.sub(r"\s+", " ", str(it).strip().lower())
        if key and key not in seen:
            seen.add(key)
            out.append(str(it).strip())
    return out


def compress_category(category: str, lines: list) -> Tuple[list, int, int]:
    joined = "\n".join(lines)
    system_prompt = COMPRESS_SYSTEM_PROMPT.format(category=category)
    out, in_tok, out_tok = call_atc_llm(
        system_prompt,
        joined,
        max_tokens=CHUNK_CATEGORIZING_MAX_OUTPUT_TOKENS
    )
    if not out:
        return lines, in_tok, out_tok
    return [l.strip("- ").strip() for l in out.splitlines() if l.strip()], in_tok, out_tok


def build_reduced_evidence_text(merged: dict) -> str:
    categories = (
        "STANDARD_DOCS",
        "ATC_PLACEHOLDER_CLARIFICATION",
        "EXEMPTION",
        "PHYSICAL_SUBMISSION",
        "COMMERCIAL_TERMS",
    )
    cat_headers = {
        "STANDARD_DOCS": "Standard Documents Evidence",
        "ATC_PLACEHOLDER_CLARIFICATION": "ATC Placeholder Clarification & Mandatory Uploads",
        "EXEMPTION": "Exemption Eligibility & Documents",
        "PHYSICAL_SUBMISSION": "Physical Submissions (Offline)",
        "COMMERCIAL_TERMS": "Key Commercial Terms & Compliance Rules",
    }
    blocks = []
    for c in categories:
        lines = merged.get(c, [])
        if lines:
            header = cat_headers.get(c, c)
            bullets = "\n".join(f"- {l}" for l in lines)
            blocks.append(f"[{header}]\n{bullets}")
    return "\n\n".join(blocks).strip()


def reduce_stage(table_result: str, merged: dict) -> Tuple[str, int, int]:
    categories = (
        "STANDARD_DOCS",
        "ATC_PLACEHOLDER_CLARIFICATION",
        "EXEMPTION",
        "PHYSICAL_SUBMISSION",
        "COMMERCIAL_TERMS",
    )
    evidence_text = build_reduced_evidence_text(merged)
    total_in = 0
    total_out = 0

    budget_check = count_tokens(ANALYSIS_SYSTEM_PROMPT) + count_tokens(table_result) + count_tokens(evidence_text)
    attempts = 0
    while budget_check > FINAL_STAGE_INPUT_TOKENS and attempts < 3:
        attempts += 1
        biggest_cat = max(categories, key=lambda c: sum(len(str(l)) for l in merged.get(c, [])))
        if not merged.get(biggest_cat):
            break
        compressed_lines, c_in, c_out = compress_category(biggest_cat, merged[biggest_cat])
        total_in += c_in
        total_out += c_out
        merged[biggest_cat] = compressed_lines
        evidence_text = build_reduced_evidence_text(merged)
        budget_check = count_tokens(ANALYSIS_SYSTEM_PROMPT) + count_tokens(table_result) + count_tokens(evidence_text)

    user_prompt = (
        f"Document required from seller:\n{table_result}\n\n"
        f"======\n\n"
        f"Additional Terms and Conditions (compacted evidence extracted from all pages):\n{evidence_text}\n"
    )

    final_res, f_in, f_out = call_atc_llm(
        ANALYSIS_SYSTEM_PROMPT,
        user_prompt,
        max_tokens=FINAL_STAGE_OUTPUT_TOKENS,
        require_json=True
    )
    return final_res, total_in + f_in, total_out + f_out


def single_shot_stage(table_result: str, atc_text: str) -> Tuple[str, int, int]:
    user_prompt = (
        f"Document required from seller:\n{table_result}\n\n"
        f"======\n\n"
        f"Additional Terms and Conditions:\n{atc_text}\n"
    )
    return call_atc_llm(
        ANALYSIS_SYSTEM_PROMPT,
        user_prompt,
        max_tokens=FINAL_STAGE_OUTPUT_TOKENS,
        require_json=True
    )


# ---------------------------------------------------------------------------
# OUTPUT FORMATTING CONVERTERS
# ---------------------------------------------------------------------------
def json_output_to_markdown_checklist(json_obj: Dict[str, Any]) -> str:
    """Convert the 5-key structured JSON output into clean, formatted markdown checklist."""
    md_lines = []

    # 1. Standard Documents
    sec1 = json_obj.get("1. Standard Documents Required", [])
    md_lines.append("### 1. Standard Documents Required")
    if sec1 and not (len(sec1) == 1 and "none specified" in str(sec1[0]).lower()):
        for doc in sec1:
            clean_d = re.sub(r"^[\*\-]\s*", "", str(doc)).strip()
            md_lines.append(f"* **{clean_d}**")
    else:
        md_lines.append("* None specified in the provided text.")
    md_lines.append("")

    # 2. Clarified ATC Documents
    sec2 = json_obj.get("2. Clarified ATC Documents & Mandatory Uploads", [])
    md_lines.append("### 2. Clarified ATC Documents & Mandatory Uploads")
    if sec2 and not (len(sec2) == 1 and "none specified" in str(sec2[0]).lower()):
        for doc in sec2:
            d_str = str(doc).strip()
            if ":" in d_str:
                k, v = d_str.split(":", 1)
                md_lines.append(f"* **{k.strip()}**: {v.strip()}")
            else:
                md_lines.append(f"* {d_str}")
    else:
        md_lines.append("* None specified in the provided text.")
    md_lines.append("")

    # 3. Exemption Documents
    sec3 = json_obj.get("3. Exemption Documents Required", [])
    md_lines.append("### 3. Exemption Documents Required")
    if sec3 and not (len(sec3) == 1 and "none specified" in str(sec3[0]).lower()):
        for doc in sec3:
            d_str = str(doc).strip()
            if ":" in d_str:
                k, v = d_str.split(":", 1)
                md_lines.append(f"* **{k.strip()}**: {v.strip()}")
            else:
                md_lines.append(f"* {d_str}")
    else:
        md_lines.append("* None specified in the provided text.")
    md_lines.append("")

    # 4. Physical Submissions
    sec4 = json_obj.get("4. Physical Submissions (Offline)", [])
    md_lines.append("### 4. Physical Submissions (Offline)")
    if sec4 and not (len(sec4) == 1 and "none specified" in str(sec4[0]).lower()):
        for item in sec4:
            if isinstance(item, dict):
                item_name = item.get("Item") or item.get("item") or "Physical Submission"
                md_lines.append(f"* **{item_name}**")
                for k in ["Deadline", "In Favor Of", "Payable At", "Delivery Address"]:
                    v = item.get(k) or item.get(k.lower().replace(" ", "_"))
                    if v:
                        md_lines.append(f"  * {k}: {v}")
            else:
                md_lines.append(f"* {item}")
    else:
        md_lines.append("* None specified in the provided text.")
    md_lines.append("")

    # 5. Commercial Terms
    sec5 = json_obj.get("5. Key Commercial Terms & Conditions to Follow", [])
    md_lines.append("### 5. Key Commercial Terms & Conditions to Follow")
    if sec5 and not (len(sec5) == 1 and "none specified" in str(sec5[0]).lower()):
        for rule in sec5:
            r_str = str(rule).strip()
            if ":" in r_str:
                k, v = r_str.split(":", 1)
                md_lines.append(f"* **{k.strip()}**: {v.strip()}")
            else:
                md_lines.append(f"* {r_str}")
    else:
        md_lines.append("* None specified in the provided text.")

    return "\n".join(md_lines).strip()


# ---------------------------------------------------------------------------
# PRIMARY PIPELINE FUNCTION
# ---------------------------------------------------------------------------
def analyze_bid_atc(
    bid_no: str,
    markdown_text: str,
    hyperlinks: Optional[List[Dict[str, str]]] = None,
    save_dir: Optional[str] = None,
    parsed_pdf_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Run end-to-end ATC compliance analysis on a bid.

    Args:
        bid_no (str): Bid identification number.
        markdown_text (str): Full markdown conversion of the tender bid.
        hyperlinks (list, optional): List of hyperlink dicts with 'name' and 'url'.
        save_dir (str, optional): Target directory to save the <bid_no>_ATC.md artifact.
        parsed_pdf_data (dict, optional): In-memory parsed PDF dictionary from the scraper.

    Returns:
        dict: Standardized result dictionary containing markdown checklist,
              structured parsed dictionary, token telemetry, and calculated costs.
    """
    safe_bid_no = (bid_no or "UNKNOWN").replace("/", "_")
    log.info(f"Starting ATC compliance analysis for {safe_bid_no}...")
    t0 = time.time()

    # 1. Extract Document Required From Seller strictly from in-memory parsed_pdf_data
    req_docs = extract_required_docs_text(parsed_pdf_data=parsed_pdf_data)

    # 2. Extract Embedded Tender ATC text
    embedded_atc = extract_embedded_atc_text(markdown_text)
    atc_parts = []
    if embedded_atc:
        atc_parts.append(("Main Bid ATC", embedded_atc))

    # 3. Check for Buyer Uploaded ATC external document
    downloaded_bytes = None
    file_type = None

    if hyperlinks:
        for link in hyperlinks:
            name = str(link.get("name", "")).lower()
            url = link.get("url")
            if ATC_PDF_LINK_NAME.lower() in name and url:
                log.info(f"Found Buyer Uploaded ATC document link: {url}")
                downloaded_bytes, file_type = download_external_doc_bytes(url, safe_bid_no, save_dir)
                break

    downloaded_chunks = []
    if downloaded_bytes:
        if file_type == "pdf":
            try:
                downloaded_chunks = extract_pdf_pages_in_memory(downloaded_bytes, safe_bid_no)
            except Exception as e:
                log.error(f"Failed extracting pages from external PDF: {e}")
        elif file_type == "docx":
            try:
                downloaded_chunks = extract_docx_in_memory(downloaded_bytes, safe_bid_no)
            except Exception as e:
                log.error(f"Failed extracting text from external DOCX: {e}")

    # 4. Merge Main Tender ATC + Downloaded Buyer ATC into ONE final unified document
    all_content_parts = []
    if atc_parts:
        all_content_parts.append(f"=== [MAIN BID ATC CLAUSES] ===\n{atc_parts[0][1]}")

    if downloaded_chunks:
        downloaded_combined = "\n\n".join(txt for _, txt in downloaded_chunks)
        all_content_parts.append(f"=== [BUYER UPLOADED ATC DOCUMENT] ===\n{downloaded_combined}")

    final_unified_text = "\n\n".join(all_content_parts).strip()

    if not final_unified_text:
        log.info(f"No ATC content found for {safe_bid_no}. Skipping LLM analysis.")
        return {
            "status": "skipped_no_atc",
            "bid_no": safe_bid_no,
            "has_atc": False,
            "elapsed_seconds": round(time.time() - t0, 2),
            "cost_usd": 0.0,
            "cost_inr": 0.0,
            "tokens": {"input": 0, "output": 0},
            "raw_markdown": "",
            "checklist": {},
            "error": None
        }

    # 5. Token-Aware Chunking: Single-Shot vs Map-Reduce
    total_tokens = count_tokens(final_unified_text)
    total_in_tokens = 0
    total_out_tokens = 0
    final_json_str = ""

    if total_tokens <= CHUNK_CATEGORIZING_MAX_INPUT_TOKENS:
        log.info(f"Running single-shot analysis ({total_tokens} tokens) via [{ATC_LLM_PROVIDER.upper()}]...")
        final_json_str, total_in_tokens, total_out_tokens = single_shot_stage(req_docs, final_unified_text)
    else:
        log.info(f"Document exceeds 1M tokens ({total_tokens} tokens). Running Map-Reduce pipeline via [{ATC_LLM_PROVIDER.upper()}]...")
        reduce_categories = (
            "STANDARD_DOCS",
            "ATC_PLACEHOLDER_CLARIFICATION",
            "EXEMPTION",
            "PHYSICAL_SUBMISSION",
            "COMMERCIAL_TERMS",
        )
        merged = {c: [] for c in reduce_categories}

        # Process main bid ATC
        if atc_parts:
            m_res, m_in, m_out = map_extract_chunk(req_docs, f"{safe_bid_no}_MAIN_ATC", atc_parts[0][1])
            total_in_tokens += m_in
            total_out_tokens += m_out
            for c in reduce_categories:
                merged[c].extend(m_res.get(c, []))

        # Process downloaded chunks
        for chunk_name, chunk_txt in downloaded_chunks:
            p_res, p_in, p_out = map_extract_chunk(req_docs, chunk_name, chunk_txt)
            total_in_tokens += p_in
            total_out_tokens += p_out
            for c in reduce_categories:
                merged[c].extend(p_res.get(c, []))

        for c in reduce_categories:
            merged[c] = dedupe_preserve_order(merged[c])

        final_json_str, r_in, r_out = reduce_stage(req_docs, merged)
        total_in_tokens += r_in
        total_out_tokens += r_out

    elapsed = round(time.time() - t0, 2)

    # 6. Parse Native Model JSON & Generate Markdown Checklist
    clean_json_body = re.sub(r"^```(json)?|```$", "", (final_json_str or "").strip(), flags=re.MULTILINE).strip()
    parsed_json_obj = {}
    try:
        parsed_json_obj = json.loads(clean_json_body)
    except Exception as e:
        log.warning(f"Could not parse LLM response as JSON: {e}")

    if parsed_json_obj:
        raw_markdown = json_output_to_markdown_checklist(parsed_json_obj)
    else:
        raw_markdown = clean_json_body

    # 7. Calculate Pricing
    active_model = OPENAI_MODEL if (ATC_LLM_PROVIDER or "").lower() == "openai" else GEMINI_MODEL
    cost_usd, cost_inr = calculate_llm_cost(ATC_LLM_PROVIDER, active_model, total_in_tokens, total_out_tokens)

    # 8. Save Artifact (<safe_bid_no>_ATC.md)
    if save_dir and os.path.exists(save_dir):
        atc_md_path = os.path.join(save_dir, f"{safe_bid_no}_ATC.md")
        try:
            with open(atc_md_path, "w", encoding="utf-8") as f:
                f.write(raw_markdown)
            log.info(f"Saved ATC compliance checklist markdown to {atc_md_path}")
        except Exception as e:
            log.warning(f"Could not save ATC markdown to {atc_md_path}: {e}")

    log.info(f"ATC analysis completed for {safe_bid_no} in {elapsed}s. Tokens: {total_in_tokens} in, {total_out_tokens} out | Cost: ${cost_usd:.5f} (₹{cost_inr:.3f})")

    return {
        "status": "success",
        "bid_no": safe_bid_no,
        "has_atc": True,
        "elapsed_seconds": elapsed,
        "cost_usd": round(cost_usd, 6),
        "cost_inr": round(cost_inr, 4),
        "tokens": {
            "input": total_in_tokens,
            "output": total_out_tokens,
        },
        "raw_markdown": raw_markdown,
        "checklist": parsed_json_obj,
        "error": None
    }
