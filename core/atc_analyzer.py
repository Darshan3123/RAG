# =========================================================================
# pipeline/atc_analyzer.py
# High-Accuracy ATC (Additional Terms and Conditions) Compliance Analyzer
# =========================================================================
"""
Modular ATC Compliance Analysis Module for GeM Bids (v3 Architecture).

Extracts (8-Category Deep Compliance Schema):
  1. STANDARD_DOCS: Standard documents required from seller (excluding * notes)
  2. ATC_DOCUMENTS_AND_UPLOADS: Mandatory certificates, undertakings, annexures, uploads
  3. EXEMPTIONS_AND_RELAXATIONS: Precise exemption rules and required proofs
  4. PHYSICAL_SUBMISSIONS: Offline instruments (EMD, PBG, samples, payee, payable at, deadlines)
  5. ELIGIBILITY_AND_QUALIFICATION: Prior experience, turnover, past performance, land border
  6. SCOPE_DELIVERY_WARRANTY_AND_SUPPORT: Scope of supply, quantities, delivery, warranty, CMC
  7. PRICING_TAX_AND_PAYMENT: Price basis, evaluation, GST/ITC, payment cycles, deductions
  8. PENALTIES_REJECTION_AND_LEGAL_TERMS: LD, PBG forfeiture, risk purchase, arbitration, jurisdiction

Supports:
  - Multi-LLM provider execution (Gemini API with thinking config & OpenAI API)
  - PyMuPDF in-memory parsing for digital pages
  - Multi-OCR provider fallback for non-digital/scanned pages (Mistral, Gemini, OpenAI)
  - External DOCX extraction using python-docx
  - Local Vertex AI tokenizer for offline token budgeting and cost calculation
  - Unified single-shot execution context (up to 1,000,000 tokens)
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
# MODEL LIMITS & GENERATION PARAMS
# ---------------------------------------------------------------------------
FINAL_STAGE_OUTPUT_TOKENS = 65536
GEN_THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "MINIMAL").strip().upper()


# Local Vertex AI Tokenizer for Gemini models
_tokenizer_model_id = "gemini-1.5-flash-002" if "flash" in (GEMINI_MODEL or "").lower() else "gemini-1.5-pro-002"
_gemini_tokenizer = tokenization.get_tokenizer_for_model(_tokenizer_model_id)

# Local tiktoken tokenizer for OpenAI models (gpt-4o covers gpt-4o and mini variants)
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
# PROMPT DEFINITION (v3 ARCHITECTURE)
# ---------------------------------------------------------------------------
ANALYSIS_SYSTEM_PROMPT = """You are an expert procurement analyst extracting bidder compliance requirements from Indian Government e-Marketplace (GeM) tender texts into strict JSON format.

GLOBAL EXTRACTION PRINCIPLES:
1. STRICT SECTION ISOLATION (ZERO HEADER LEAK):
   - The text under "Document required from seller:" is used ONLY for "STANDARD_DOCS".
   - NEVER extract any document, requirement, condition, or exemption from the "Document required from seller:" section into "ATC_DOCUMENTS_AND_UPLOADS" or "EXEMPTIONS_AND_RELAXATIONS".
   - Discard all text lines beginning with or containing "*".
   - All entries for categories other than "STANDARD_DOCS" must come EXCLUSIVELY from the body of "Additional Terms and Conditions:".

2. PRESERVE ALL CONFLICTS AND DISCREPANCIES ACROSS ALL CATEGORIES:
   - Government tenders frequently contain contradictory clauses across the main ATC, uploaded PDFs, specifications, and annexures.
   - NEVER resolve, reconcile, merge, or choose between conflicting terms.
   - If ANY parameter, requirement, duration (e.g., conflicting warranty periods), deadline, frequency, or quantity has differing values across different sections of the text, extract every single variation as an independent entry in its respective category.
   - NEVER omit an earlier clause simply because a later clause appears to update or override it.

3. FIDELITY & EXTRACTION DEPTH:
   - Extract factual, standalone requirement statements.
   - Do not hallucinate external policies or GeM standard rules.
   - Include specific item numbers, mandatory spare quantities, and accessories listed in schedules/annexures.
   - Exclude clause numbers, page markers, and editorial comments.
   - Return raw, valid JSON only without markdown formatting.

4. STRICT JSON DATA TYPE RULES:
   - "PHYSICAL_SUBMISSIONS" is the ONLY category that contains JSON objects.
   - ALL OTHER categories (including "EXEMPTIONS_AND_RELAXATIONS") MUST be flat arrays of strings. Never output objects inside "EXEMPTIONS_AND_RELAXATIONS".

JSON SCHEMA:
{
  "STANDARD_DOCS": [
    // Items taken EXCLUSIVELY from the "Document required from seller:" list.
    // Exclude any item containing "(Requested in ATC)" and any line starting with "*".
    // If nothing remains, return [].
  ],
  "ATC_DOCUMENTS_AND_UPLOADS": [
    // Every certificate, undertaking, annexure format, datasheet, test report, or document explicitly mandated for upload in the "Additional Terms and Conditions:" body.
  ],
  "EXEMPTIONS_AND_RELAXATIONS": [
    // Flat array of strings ONLY (format: "Exemption: <details> | Proof: <proof document>").
    // Must originate strictly from the ATC text.
    // If no document is named in the text, append: "supporting document not specified in text".
  ],
  "PHYSICAL_SUBMISSIONS": [
    // Every offline/hard-copy requirement (EMD DD/FDR/BG, notarized agreements, physical samples).
    // If different clauses state different submission deadlines or addresses for the same item, output a separate object for each variation.
    // Schema:
    // {
    //   "Item": "Name of physical submission item",
    //   "Deadline": "Submission deadline or 'Not specified in source text.'",
    //   "In Favor Of": "Payee/Beneficiary or 'Not specified in source text.'",
    //   "Payable At": "Payable location/bank or 'Not specified in source text.'",
    //   "Delivery Address": "Office/location address or 'Not specified in source text.'",
    //   "Original Text": "Brief verbatim sentence stating this physical requirement."
    // }
  ],
  "ELIGIBILITY_AND_QUALIFICATION": [
    // Prior turnover, past experience period, past performance ratio, authorization criteria, land border rule, or bidder exclusion clause.
  ],
  "SCOPE_DELIVERY_WARRANTY_AND_SUPPORT": [
    // Scope of work/supply, quantities, required accessories/spares/consumables, delivery schedules, Option Clause terms, testing/inspection, all stated warranty durations, all stated CMC terms, uptime percentages, and service center terms.
  ],
  "PRICING_TAX_AND_PAYMENT": [
    // Price basis, evaluation methodology, GST/statutory variation rules, ITC terms, all stated payment cycles/schedules, bill passing prerequisites, deductions.
  ],
  "PENALTIES_REJECTION_AND_LEGAL_TERMS": [
    // EMD/PBG forfeiture, Liquidated Damages (LD), risk purchase, abnormally low bid terms, rejection grounds, Integrity Pact, arbitration, jurisdiction, governing law.
  ]
}"""


# ---------------------------------------------------------------------------
# EXTRACTION HELPERS
# ---------------------------------------------------------------------------
def extract_required_docs_text(parsed_pdf_data: Optional[Dict[str, Any]] = None) -> str:
    """
    Extract 'Document required from seller' strictly from in-memory parsed_pdf_data,
    stripping trailing inline notes that begin with '*' (e.g. *In case any bidder...).
    """
    if parsed_pdf_data and isinstance(parsed_pdf_data, dict):
        docs = (
            parsed_pdf_data.get("documents", {}).get("required_from_seller", [])
            or parsed_pdf_data.get("pdf", {}).get("documents", {}).get("required_from_seller", [])
        )
        if isinstance(docs, list) and docs:
            cleaned_items = []
            for d in docs:
                text = str(d).strip()
                text = re.split(r'\*', text)[0].strip()
                if text:
                    cleaned_items.append(f"- {text}")
            return "Document required from seller:\n" + ("\n".join(cleaned_items) if cleaned_items else "None specified")
        elif isinstance(docs, str) and docs.strip():
            cleaned_text = re.split(r'\*', docs.strip())[0].strip()
            return f"Document required from seller:\n{cleaned_text}"

    return "Document required from seller:\nNone specified"


def extract_required_docs_from_json(json_filepath: str) -> str:
    """Extract required documents list from tender JSON structure, stripping inline notes."""
    if not os.path.exists(json_filepath):
        return "Document required from seller:\nNone specified"

    try:
        with open(json_filepath, "r", encoding="utf-8") as jf:
            data = json.load(jf)

        docs = data.get("pdf", {}).get("documents", {}).get("required_from_seller", [])
        if not docs:
            docs = data.get("documents", {}).get("required_from_seller", [])

        if isinstance(docs, list) and docs:
            cleaned_items = []
            for d in docs:
                text = str(d).strip()
                text = re.split(r'\*', text)[0].strip()
                if text:
                    cleaned_items.append(f"- {text}")
            return "Document required from seller:\n" + ("\n".join(cleaned_items) if cleaned_items else "None specified")
        elif isinstance(docs, str) and docs.strip():
            cleaned_text = re.split(r'\*', docs.strip())[0].strip()
            return f"Document required from seller:\n{cleaned_text}"
        else:
            return "Document required from seller:\nNone specified"
    except Exception as e:
        return f"Document required from seller:\nError reading JSON: {e}"


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

        # Stream downloaded external document to MinIO S3 (Zero-Disk)
        target_ext = "docx" if file_type == "docx" else "pdf"
        try:
            from utils.s3_storage import upload_bytes
            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if file_type == "docx" else "application/pdf"
            upload_bytes(f"bids/{safe_bid_no}/atc_document.{target_ext}", resp.content, content_type=mime)
        except Exception as s3_err:
            log.warning(f"Could not stream external ATC doc to MinIO: {s3_err}")

        # Optionally save downloaded external document into local directory if requested
        if save_dir and os.path.exists(save_dir):
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
    """Extract text and tables from DOCX in memory using python-docx."""
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
            return [(f"{base_name}_BUYER_UPLOADED_DOC", full_docx_text)]
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
    - Merged into a single consolidated BUYER_UPLOADED_DOC chunk.
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

    page_items = [(page_idx + 1, page_text) for page_idx, page_text in digital_page_texts.items()]

    # Process non-digital pages in-memory if any
    if non_digital_page_indices:
        log.info(f"Found {len(non_digital_page_indices)} non-digital page(s): {[p + 1 for p in non_digital_page_indices]}. Running in-memory OCR...")
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

    combined_text = "\n\n".join(f"--- [Page {p_num}] ---\n{p_text}\n" for p_num, p_text in page_items).strip()
    label = f"{base_name}_BUYER_UPLOADED_DOC"
    return [(label, combined_text)]


# ---------------------------------------------------------------------------
# LLM INFERENCE CLIENTS (GEMINI & OPENAI)
# ---------------------------------------------------------------------------
def call_gemini(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = FINAL_STAGE_OUTPUT_TOKENS,
    require_json: bool = True,
    retries: int = 3
) -> Tuple[str, int, int]:
    """Call Google Gemini API with v3 thinking-mode support. Returns (output_text, input_tokens, output_tokens)."""
    if not GEMINI_API_KEY:
        log.error("GEMINI_API_KEY is not set.")
        return "", 0, 0

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
        }
    }

    if GEN_THINKING_LEVEL:
        payload["generationConfig"]["thinkingConfig"] = {"thinkingLevel": GEN_THINKING_LEVEL}

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
                    if candidates[0].get("finishReason") == "MAX_TOKENS":
                        log.warning("Gemini hit the output token cap; the JSON may be truncated.")
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        text_val = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
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
    max_tokens: int = FINAL_STAGE_OUTPUT_TOKENS,
    temperature: float = 0.0,
    require_json: bool = True,
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
    max_tokens: int = FINAL_STAGE_OUTPUT_TOKENS,
    require_json: bool = True
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
    in_rate = model_pricing.get("input_per_million", 0.15)
    out_rate = model_pricing.get("output_per_million", 1.50)

    usd = (in_tokens * in_rate / 1_000_000) + (out_tokens * out_rate / 1_000_000)
    inr = usd * USD_TO_INR_RATE
    return usd, inr


def single_shot_stage(req_docs: str, unified_atc_body: str) -> Tuple[str, int, int]:
    """Sends the fully unified prompt to the active LLM."""
    user_prompt = (
        f"{req_docs}\n\n"
        f"======\n\n"
        f"Additional Terms and Conditions:\n"
        f"{unified_atc_body}"
    ).strip()
    return call_atc_llm(
        ANALYSIS_SYSTEM_PROMPT,
        user_prompt,
        max_tokens=FINAL_STAGE_OUTPUT_TOKENS,
        require_json=True
    )






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
    Run end-to-end ATC compliance analysis on a bid using the v3 single-shot engine.

    Args:
        bid_no (str): Bid identification number.
        markdown_text (str): Full markdown conversion of the tender bid.
        hyperlinks (list, optional): List of hyperlink dicts with 'name' and 'url'.
        save_dir (str, optional): Target directory to save the <bid_no>_ATC.md and JSON artifacts.
        parsed_pdf_data (dict, optional): In-memory parsed PDF dictionary from the scraper.

    Returns:
        dict: Standardized result dictionary containing markdown checklist,
              structured parsed dictionary, token telemetry, and calculated costs.
    """
    safe_bid_no = (bid_no or "UNKNOWN").replace("/", "_")
    log.info(f"Starting ATC compliance analysis (v3) for {safe_bid_no}...")
    t0 = time.time()

    # 1. Extract Document Required From Seller
    req_docs = extract_required_docs_text(parsed_pdf_data=parsed_pdf_data)
    if "none specified" in req_docs.lower() and save_dir:
        json_candidate = os.path.join(save_dir, f"{safe_bid_no}.json")
        if os.path.exists(json_candidate):
            req_docs = extract_required_docs_from_json(json_candidate)

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

    # 4. Merge Main Tender ATC + Downloaded Buyer ATC into ONE unified payload
    all_content_parts = []
    if atc_parts:
        all_content_parts.append(f"=== [MAIN BID ATC CLAUSES] ===\n{atc_parts[0][1]}")

    if downloaded_chunks:
        downloaded_combined = "\n\n".join(txt for _, txt in downloaded_chunks)
        all_content_parts.append(f"=== [BUYER UPLOADED ATC DOCUMENT] ===\n{downloaded_combined}")

    unified_body = "\n\n".join(all_content_parts).strip()

    if not unified_body:
        log.info(f"No ATC content found for {safe_bid_no}. Skipping LLM analysis.")
        return {
            "status": "skipped_no_atc",
            "bid_no": safe_bid_no,
            "has_atc": False,
            "elapsed_seconds": round(time.time() - t0, 2),
            "cost_usd": 0.0,
            "cost_inr": 0.0,
            "tokens": {"input": 0, "output": 0},
            "checklist": {},
            "error": None
        }

    # 5. Execute Single-Shot Inference (Context Budget up to 1,000,000 tokens)
    total_tokens = count_tokens(unified_body)
    log.info(f"Running single-shot analysis ({total_tokens} tokens) via [{ATC_LLM_PROVIDER.upper()}]...")
    final_json_str, total_in_tokens, total_out_tokens = single_shot_stage(req_docs, unified_body)

    elapsed = round(time.time() - t0, 2)

    # 6. Parse Native Model JSON
    clean_json_body = re.sub(r"^```(json)?|```$", "", (final_json_str or "").strip(), flags=re.MULTILINE).strip()
    parsed_json_obj = {}
    try:
        parsed_json_obj = json.loads(clean_json_body)
    except Exception as e:
        log.warning(f"Could not parse LLM response as JSON: {e}")

    # 7. Calculate Pricing
    active_model = OPENAI_MODEL if (ATC_LLM_PROVIDER or "").lower() == "openai" else GEMINI_MODEL
    cost_usd, cost_inr = calculate_llm_cost(ATC_LLM_PROVIDER, active_model, total_in_tokens, total_out_tokens)

    # 8. Save Artifact (<safe_bid_no>_INFER_OUTPUT.json)
    if save_dir and os.path.exists(save_dir) and parsed_json_obj:
        atc_json_path = os.path.join(save_dir, f"{safe_bid_no}_INFER_OUTPUT.json")
        try:
            with open(atc_json_path, "w", encoding="utf-8") as f:
                json.dump(parsed_json_obj, f, indent=2, ensure_ascii=False)
            log.info(f"Saved ATC compliance structured JSON to {atc_json_path}")
        except Exception as e:
            log.warning(f"Could not save ATC JSON to {atc_json_path}: {e}")

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
        "checklist": parsed_json_obj,
        "error": None
    }
