"""
ANALYZE_CHUNKS.py
------------------
Consumes the per-document chunk folders produced by CHUNKS_EXTRACTOR.py
(under OUTPUT_EXTRACTED_CHUNKS_TXT/<base_name>/...) and runs the final
procurement-analysis prompt against the local llama-server.

Two modes, chosen automatically per document folder:

  SINGLE-SHOT  -> only one ATC chunk exists (markdown-only case, no PDF).
                  The full analysis prompt is run once, directly.

  MAP-REDUCE   -> multiple page chunks exist (PDF case).
                  Stage 1 (MAP):    The Markdown chunk is processed first as a standalone. 
                                    Remaining PDF chunks are processed using a dynamic 
                                    self-healing queue. It batches up to the maximum 
                                    context limit. If the model breaks JSON format, the 
                                    batch shrinks by 1 chunk, pushes the removed chunk 
                                    to the next batch, and retries until successful.
                  Stage 2 (REDUCE): all buckets are merged + de-duplicated
                                    across pages, and the ORIGINAL full
                                    analysis prompt is run once on the
                                    compacted evidence instead of raw ATC text.
                  Stage 2b (SAFETY): if merged evidence overflows context window,
                                    it is split into batches and pre-compressed
                                    with an extra reduce pass before final analysis.

Requires: local llama-server running (OpenAI-compatible /v1/chat/completions endpoint).
"""

import sys
import subprocess
import os
import re
import json
import glob
import time
import multiprocessing

# --- Auto-install deps ---
def install_and_import(package, import_name):
    try:
        __import__(import_name)
    except ImportError:
        print(f"{package} is missing. Installing it now...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

install_and_import("requests", "requests")
install_and_import("transformers", "transformers")
install_and_import("beautifulsoup4", "bs4")
install_and_import("pymupdf", "pymupdf")
install_and_import("tabulate", "tabulate")

import requests
import pymupdf
from bs4 import BeautifulSoup
from transformers import AutoTokenizer
from tabulate import tabulate

# =========================================================================
# CONFIG
# =========================================================================
ANALYSIS_OUTPUT_DIR = "OUTPUT"                   # where final .md analyses are written
LLAMA_SERVER_URL = "http://localhost:8080"
CHAT_ENDPOINT = f"{LLAMA_SERVER_URL}/v1/chat/completions"

CONTEXT_WINDOW = 9216

# The tokenizer must match the model actually being served by llama-server
QWEN_TOKENIZER_NAME = "Qwen/Qwen3-4B"

# Reserve tokens for chat-template overhead
TEMPLATE_OVERHEAD_TOKENS = 100

# Output caps
MAP_MAX_OUTPUT_TOKENS = 2000         # map stage: short JSON evidence dump
REDUCE_MAX_OUTPUT_TOKENS = 2000      # reduce/single-shot: full 5-section checklist

# Input budgets derived from CONTEXT_WINDOW (Provides exactly 7,116 tokens for MAP input)
MAP_MAX_INPUT_TOKENS = CONTEXT_WINDOW - MAP_MAX_OUTPUT_TOKENS - TEMPLATE_OVERHEAD_TOKENS
REDUCE_MAX_INPUT_TOKENS = CONTEXT_WINDOW - REDUCE_MAX_OUTPUT_TOKENS - TEMPLATE_OVERHEAD_TOKENS

REQUIRED_DOCS_HEADER = "Document required from seller"
ATC_SECTION_HEADER = "Buyer Added Bid Specific Terms and Conditions"

# =========================================================================
# EXTRACTION-STAGE CONFIG
# =========================================================================
INPUT_MARKDOWNS_DIR = "TEST_MARKDOWNS_EXTRA"   # source .md (+ sibling .json) files
ATC_SECTION_START_MARKER = "Buyer Added Bid Specific Terms and Conditions"
ATC_SECTION_END_MARKER = "अस्वीकरण/Disclaimer"
ATC_PDF_LINK_NAME = "Buyer uploaded ATC document"

CATEGORIES = [
    "STANDARD_DOCS",
    "ATC_PLACEHOLDER_CLARIFICATION",
    "EXEMPTION",
    "PHYSICAL_SUBMISSION",
    "COMMERCIAL_TERMS",
]

print(f"Loading tokenizer for {QWEN_TOKENIZER_NAME} (used for context-window budgeting)...")
_enc = AutoTokenizer.from_pretrained(QWEN_TOKENIZER_NAME, trust_remote_code=True)


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_enc.encode(text, add_special_tokens=False))


# =========================================================================
# PROGRESS SPINNER
# =========================================================================
def _run_spinner(description, stop_event):
    start_time = time.time()
    spinner = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    idx = 0
    
    # Truncate description to prevent terminal line wrapping which breaks \r
    if len(description) > 70:
        description = description[:67] + "..."
        
    while not stop_event.is_set():
        elapsed = time.time() - start_time
        # \033[2K clears the entire line, \r resets cursor to start
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


def record_call(label: str, system_prompt: str, user_prompt: str, output_text: str,
                 elapsed_seconds: float) -> None:
    global GRAND_TOTAL_SECONDS
    in_tokens = count_tokens(system_prompt) + count_tokens(user_prompt)
    out_tokens = count_tokens(output_text)
    TOKEN_RECORDS.append((label, in_tokens, out_tokens, elapsed_seconds))
    GRAND_TOTAL_SECONDS += elapsed_seconds


def print_token_table(records, title: str) -> None:
    if not records:
        return

    headers = ["Stage", "Input Tokens", "Output Tokens", "Time (s)"]
    rows = [(label, str(i), str(o), f"{t:.2f}") for label, i, o, t in records]
    
    total_in = sum(i for _, i, _, _ in records)
    total_out = sum(o for _, _, o, _ in records)
    total_time = sum(t for _, _, _, t in records)
    rows.append(("TOTAL", str(total_in), str(total_out), f"{total_time:.2f}"))

    print(f"\n    Token Usage — {title}")
    
    # Use tabulate with fancy_grid and maxcolwidths to auto-wrap long text
    table_str = tabulate(rows, headers=headers, tablefmt="fancy_grid", maxcolwidths=[60, None, None, None])
    
    # Maintain consistent indentation
    for line in table_str.splitlines():
        print(f"    {line}")
    print()


# =========================================================================
# LLAMA-SERVER CALL
# =========================================================================
def call_llm(system_prompt: str, user_prompt: str, max_tokens: int,
             frequency_penalty: float = 0.0, seed: int = 42, require_json: bool = False) -> str:
    payload = {
        "model": "local-qwen3-4b",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "top_p": 0.95,
        "top_k": 20,
        "min_p": 0,
        "repeat_penalty": 1.0,
        "presence_penalty": 1.5,
        "frequency_penalty": frequency_penalty,
        "max_tokens": max_tokens,
        "seed": seed,
    }
    
    if require_json:
        payload["response_format"] = {"type": "json_object"}
        
    try:
        resp = requests.post(CHAT_ENDPOINT, json=payload, timeout=300)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"    [-] llama-server call failed: {e}")
        return ""


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
c. Section 3: never combine "None specified" with a (Explicit)/(Inferred) tag in the same line. Always output a real document name with exactly one tag.
d. Section 4: "In Favor Of" = payee on the instrument only, never a mailing recipient.
These four corrections happen silently in your draft. They are never described, explained, or mentioned in the output.

Formatting & Output Rules:
- CRITICAL CONCISENESS: Do NOT write full sentences for document lists. Do NOT use conversational filler (e.g., "Here is the summary...", "This placeholder requires..."). Output the data directly.
- ABSOLUTE RULE — NO META-COMMENTARY: The output must contain ONLY the five "###" headings and their bullets. Never include the words "Note:", "Final output:", or any explanation of a decision, exclusion, or inference. Never use ❌ or ✅ symbols. Never explain why something was included, excluded, or inferred — the tags "(Explicit)" and "(Inferred)" in Section 3 are the ONLY allowed annotations anywhere in the output. If you catch yourself about to write a sentence explaining your own reasoning, delete that sentence before outputting.
- Do NOT output Steps 1-3 or any internal reasoning. Output only the five formatted sections below.
- Use Markdown extensively. Use ### for main headings and * for bulleted lists.
- Use **Bold Text** to highlight key entities (document names, placeholders, deadlines, percentages, and authorities).
- If multiple formats apply to one category, separate them with commas.
- If a section has no relevant data in the provided text, output "None specified in the provided text." strictly under that heading — except Section 3, which follows its own rule below and must never use this fallback when an exemption category is present in the top section.

Required Output Structure:
Categorize the extracted information exactly into the following five sections:

### 1. Standard Documents Required
From the top section's comma-separated list, output only items that do NOT contain "(Requested in ATC)". Items containing that phrase are never output here (they belong in Section 2 only).

Input: "PAN Card, GSTIN Copy, Certificate (Requested in ATC)" → Output:
* PAN Card
* GSTIN Copy

Input: "Certificate (Requested in ATC)" → Output:
* None specified in the provided text.

* [Exact Document Name]

### 2. Clarified ATC Documents & Mandatory Uploads
Analyze the top section for every placeholder tagged "(Requested in ATC)" — regardless of its label (e.g. "Certificate", "Additional Doc 1", "Additional Doc 2", or any other name). For each one, read the bottom ATC text and deduce EXACTLY what specific certificate or document is being requested, based on a clause that actually describes a document — not the exemption-eligibility sentence. Also, list any other mandatory certificates, registrations, declarations, undertakings, or digital uploads mentioned anywhere in the ATC text, even if mentioned only in passing within a clause about another topic.
* **[Placeholder Name from Top Section]**: [Exact document name 1, Exact document name 2]
* **[Other Upload Required in ATC]**: [Brief description/criteria, e.g., "last 3 years", "CA certified"]

### 3. Exemption Documents Required
Look for exemption clauses in the top list (e.g., "*In case any bidder is seeking exemption from Experience / Turnover Criteria..."). Determine what document is required to claim each exemption:
- If the ATC text explicitly names the required document, use that exact name.
- If the ATC text mentions the exemption category but does not specify a document, you MUST name the standard document conventionally required under GeM/government procurement practice (e.g. Udyam/MSE Registration Certificate for MSE exemption, DPIIT Startup Recognition Certificate for Start-up exemption). A named document is always required in this section when the exemption clause is present in the top section; "None specified" is never a valid entry here in that case.
* **Proof for Exemption (MSEs)**: [Exact certificate name]
* **Proof for Exemption (Start-ups)**: [Exact certificate name]

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
Extract strict operational, pricing, or compliance rules the bidder must adhere to from the ATC text. Include minor procedural instructions as well (e.g. required envelope superscription, required fields in a payment portal's remarks section, specific codes to be used) — these can cause bid rejection if missed and must not be summarized away.
* **[Topic, e.g., GST / Option Clause / Scope of Supply]**: [Clear, concise explanation of the rule, penalty, or requirement]
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
# IN-MEMORY CHUNK EXTRACTION
# =========================================================================
def extract_table_value(filepath: str, search_key: str) -> str:
    if not os.path.exists(filepath):
        return f"Error: The file '{filepath}' was not found.\n"

    with open(filepath, "r", encoding="utf-8") as file:
        content = file.read()

    soup = BeautifulSoup(content, "html.parser")
    for row in soup.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) == 2:
            key = cols[0].text.strip()
            if search_key.lower() in key.lower():
                value = cols[1].text.strip()
                return f"{key} : {value}"

    return f"'{search_key}' not found in the document."


def extract_text_chunk(filepath: str, start_marker: str, end_marker: str) -> str:
    if not os.path.exists(filepath):
        return f"Error: The file '{filepath}' was not found.\n"

    with open(filepath, "r", encoding="utf-8") as file:
        content = file.read()

    start_idx = content.find(start_marker)
    if start_idx == -1:
        return f"Error: Start marker '{start_marker}' not found in the document."

    content_start_idx = start_idx + len(start_marker)
    end_idx = content.find(end_marker, content_start_idx)
    if end_idx == -1:
        return f"Error: End marker '{end_marker}' not found after the start marker."

    return content[content_start_idx:end_idx].strip()


def download_pdf_bytes(url: str):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, timeout=15, headers=headers)
        resp.raise_for_status()

        if "login" in resp.url.lower():
            print(f"    [-] Skipped: Redirected to login page -> {url}")
            return None

        content_type = resp.headers.get("Content-Type", "").lower()
        if "text/html" in content_type:
            print(f"    [-] Skipped: URL requires authentication -> {url}")
            return None

        return resp.content
    except Exception as e:
        print(f"    [-] Failed to download {url}: {e}")
        return None


def extract_pdf_pages_in_memory(pdf_bytes: bytes, base_name: str):
    chunks = []
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        for page_num in range(1, len(doc) + 1):
            page_text = doc.load_page(page_num - 1).get_text("text").strip()
            chunks.append((f"{base_name}_ATC_CHUNK_{page_num}", page_text))
        doc.close()
    except Exception as e:
        print(f"    [-] Error extracting text from PDF: {e}")
    return chunks


def extract_document_chunks_in_memory(md_filepath: str):
    base_name = os.path.splitext(os.path.basename(md_filepath))[0]

    table_result = extract_table_value(md_filepath, REQUIRED_DOCS_HEADER)
    md_chunk_result = extract_text_chunk(md_filepath, ATC_SECTION_START_MARKER, ATC_SECTION_END_MARKER)

    if not md_chunk_result.startswith("Error:"):
        md_chunk_result = re.sub(
            r"Buyer uploaded ATC document\s*\[?Click here to view the file\]?\([^)]*\)?",
            "", md_chunk_result, flags=re.IGNORECASE,
        )
        md_chunk_result = md_chunk_result.replace(
            "Buyer uploaded ATC document Click here to view the file", ""
        ).strip()

    chunks = []
    if md_chunk_result and not md_chunk_result.startswith("Error:"):
        chunks.append((f"{base_name}_ATC_MARKDOWN_CHUNK", md_chunk_result))

    json_filepath = os.path.join(os.path.dirname(md_filepath), f"{base_name}.json")
    pdf_bytes = None
    if os.path.exists(json_filepath):
        try:
            with open(json_filepath, "r", encoding="utf-8") as jf:
                data = json.load(jf)
            for link in data.get("hyperlinks", []):
                name = link.get("name", "")
                url = link.get("url")
                if ATC_PDF_LINK_NAME.lower() in name.lower() and url:
                    pdf_bytes = download_pdf_bytes(url)
                    break
        except json.JSONDecodeError:
            print(f"    [-] Error: Failed to parse JSON in {json_filepath}")
        except Exception as e:
            print(f"    [-] Unexpected error processing JSON: {e}")
    else:
        print(f"    [-] No corresponding JSON file found at {json_filepath}")

    if pdf_bytes:
        chunks.extend(extract_pdf_pages_in_memory(pdf_bytes, base_name))

    if not chunks:
        chunks.append((f"{base_name}_ATC_CHUNK_1", "No Valid ATC Found"))

    return table_result, chunks


# =========================================================================
# MAP STAGE
# =========================================================================
def map_extract_chunk(table_result: str, chunk_label: str, atc_text: str, strict: bool = False) -> dict:
    empty = {c: [] for c in CATEGORIES}

    system_prompt = MAP_SYSTEM_PROMPT.format(table_result=table_result)
    budget_check = count_tokens(system_prompt) + count_tokens(atc_text)

    if budget_check > MAP_MAX_INPUT_TOKENS:
        allowed_chars = int(len(atc_text) * (MAP_MAX_INPUT_TOKENS / budget_check) * 0.95)
        atc_text = atc_text[:allowed_chars]
        print(f"    [!] {chunk_label}: text truncated to fit map-stage context budget")

    _t0 = time.time()
    timer = ProgressTimer(f"Processing {chunk_label} (MAP stage, llama.cpp)")
    timer.start()
    raw = call_llm(system_prompt, atc_text, max_tokens=MAP_MAX_OUTPUT_TOKENS, require_json=True)
    timer.stop()
    record_call(f"MAP: {chunk_label}", system_prompt, atc_text, raw, time.time() - _t0)
    
    if not raw:
        if strict: 
            raise ValueError("Empty response")
        return empty

    raw_clean = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(raw_clean)
        result = {}
        for c in CATEGORIES:
            v = parsed.get(c, [])
            result[c] = v if isinstance(v, list) else [str(v)]
        return result
    except Exception:
        # If running in a dynamic retry queue, force an error upward to trigger the batch shrink.
        if strict:
            raise ValueError("Invalid JSON format from model")
            
        print(f"    [!] {chunk_label}: map-stage output wasn't valid JSON, keeping raw text as fallback evidence")
        fallback = empty
        fallback["COMMERCIAL_TERMS"] = [f"[UNPARSED PAGE OUTPUT - {chunk_label}] {raw_clean[:1500]}"]
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
# REDUCE STAGE
# =========================================================================
def compress_category(category: str, lines: list) -> list:
    joined = "\n".join(lines)
    system_prompt = COMPRESS_SYSTEM_PROMPT.format(category=category)
    _t0 = time.time()
    timer = ProgressTimer(f"Compressing category '{category}' (llama.cpp)")
    timer.start()
    out = call_llm(system_prompt, joined, max_tokens=MAP_MAX_OUTPUT_TOKENS)
    timer.stop()
    record_call(f"COMPRESS: {category}", system_prompt, joined, out, time.time() - _t0)
    if not out:
        return lines
    return [l.strip("- ").strip() for l in out.splitlines() if l.strip()]


def build_reduced_evidence_text(merged: dict) -> str:
    parts = []
    for c in CATEGORIES:
        lines = merged.get(c, [])
        parts.append(f"[{c}]")
        if lines:
            parts.extend(f"- {l}" for l in lines)
        else:
            parts.append("- (none found)")
        parts.append("")
    return "\n".join(parts).strip()


def reduce_stage(table_result: str, merged: dict) -> str:
    evidence_text = build_reduced_evidence_text(merged)
    budget_check = count_tokens(ANALYSIS_SYSTEM_PROMPT) + count_tokens(table_result) + count_tokens(evidence_text)

    attempts = 0
    while budget_check > REDUCE_MAX_INPUT_TOKENS and attempts < 3:
        attempts += 1
        biggest_cat = max(CATEGORIES, key=lambda c: sum(len(l) for l in merged.get(c, [])))
        if not merged.get(biggest_cat):
            break
        print(f"    [!] Evidence too large for reduce stage, compressing category '{biggest_cat}' (pass {attempts})")
        merged[biggest_cat] = compress_category(biggest_cat, merged[biggest_cat])
        evidence_text = build_reduced_evidence_text(merged)
        budget_check = count_tokens(ANALYSIS_SYSTEM_PROMPT) + count_tokens(table_result) + count_tokens(evidence_text)

    user_prompt = (
        f"Document required from seller:\n{table_result}\n\n"
        f"======\n\n"
        f"Additional Terms and Conditions (compacted evidence extracted from all pages):\n{evidence_text}\n"
    )

    _t0 = time.time()
    timer = ProgressTimer("Running Combining Stage - final analysis (llama.cpp)")
    timer.start()
    result = call_llm(ANALYSIS_SYSTEM_PROMPT, user_prompt, max_tokens=REDUCE_MAX_OUTPUT_TOKENS,
                       frequency_penalty=1.0)
    timer.stop()
    record_call("Combining Stage", ANALYSIS_SYSTEM_PROMPT, user_prompt, result, time.time() - _t0)
    return result


# =========================================================================
# SINGLE-SHOT (markdown-only, no PDF chunks)
# =========================================================================
def single_shot_stage(table_result: str, atc_text: str) -> str:
    total = count_tokens(ANALYSIS_SYSTEM_PROMPT) + count_tokens(table_result) + count_tokens(atc_text)
    if total > REDUCE_MAX_INPUT_TOKENS:
        print(f"    [!] Single chunk is large (~{total} tokens) - routing through map/reduce instead of one-shot")
        merged = map_extract_chunk(table_result, "single_chunk", atc_text)
        for c in CATEGORIES:
            merged[c] = dedupe_preserve_order(merged[c])
        return reduce_stage(table_result, merged)

    user_prompt = (
        f"Document required from seller:\n{table_result}\n\n"
        f"======\n\n"
        f"Additional Terms and Conditions:\n{atc_text}\n"
    )
    _t0 = time.time()
    timer = ProgressTimer("Running SINGLE-SHOT analysis (llama.cpp)")
    timer.start()
    result = call_llm(ANALYSIS_SYSTEM_PROMPT, user_prompt, max_tokens=REDUCE_MAX_OUTPUT_TOKENS,
                       frequency_penalty=1.0)
    timer.stop()
    record_call("SINGLE-SHOT (final)", ANALYSIS_SYSTEM_PROMPT, user_prompt, result, time.time() - _t0)
    return result


# =========================================================================
# MAIN
# =========================================================================
def process_document(md_filepath: str, base_name: str):
    TOKEN_RECORDS.clear()

    timer = ProgressTimer(f"Generating chunks for {base_name}")
    timer.start()
    table_result, chunks = extract_document_chunks_in_memory(md_filepath)
    timer.stop()

    chunks = [(name, atc) for name, atc in chunks if atc]  # drop empty parses

    if not chunks:
        print(f"    [-] No usable chunk text found in {md_filepath}, skipping.")
        return

    if len(chunks) == 1:
        print(f"    -> Single chunk detected ({chunks[0][0]}): running one-shot analysis")
        final_answer = single_shot_stage(table_result, chunks[0][1])
    else:
        print(f"    -> {len(chunks)} chunks detected. Processing Markdown first, then batching PDF pages.")
        merged = {c: [] for c in CATEGORIES}
        
        # 1. Separate Markdown chunk from PDF chunks
        md_chunk = next((c for c in chunks if "ATC_MARKDOWN_CHUNK" in c[0]), None)
        pdf_chunks = [c for c in chunks if "ATC_MARKDOWN_CHUNK" not in c[0]]
        
        # 2. Run Markdown chunk alone first (if it exists)
        if md_chunk:
            print(f"    -> Isolating explicit terms. Running standalone MAP stage for: {md_chunk[0]}")
            md_result = map_extract_chunk(table_result, md_chunk[0], md_chunk[1], strict=False)
            for c in CATEGORIES:
                merged[c].extend(md_result.get(c, []))
        
        # 3. Dynamic Self-Healing Queue for the remaining PDF chunks
        if pdf_chunks:
            base_prompt_tokens = count_tokens(MAP_SYSTEM_PROMPT.format(table_result=table_result))
            pending_chunks = pdf_chunks.copy()
            
            while pending_chunks:
                current_batch_names = []
                current_batch_texts = []
                current_tokens = base_prompt_tokens
                
                # Fill the batch up to the absolute API input limit
                for name, atc_text in pending_chunks:
                    chunk_addition = f"\n\n--- [START {name}] ---\n{atc_text}\n--- [END {name}] ---\n"
                    chunk_tokens = count_tokens(chunk_addition)
                    
                    # If it exceeds budget and we already have a chunk, stop packing
                    if current_tokens + chunk_tokens > (MAP_MAX_INPUT_TOKENS - 200) and current_batch_names:
                        break
                        
                    current_batch_names.append(name)
                    current_batch_texts.append(chunk_addition)
                    current_tokens += chunk_tokens
                
                # Process the populated batch, shrinking it down dynamically if the model fails JSON structure
                success = False
                while current_batch_names and not success:
                    batch_label = " + ".join(current_batch_names)
                    batch_text = "".join(current_batch_texts)
                    
                    try:
                        # strict=True means it will throw a ValueError instead of passing bad fallback text
                        page_result = map_extract_chunk(table_result, batch_label, batch_text, strict=True)
                        for c in CATEGORIES:
                            merged[c].extend(page_result.get(c, []))
                            
                        success = True
                        
                        # Remove only the chunks that were successfully processed from the queue
                        pending_chunks = pending_chunks[len(current_batch_names):]
                        
                    except ValueError:
                        # The model was overwhelmed and failed to follow JSON rules. 
                        # We pop the last chunk out of the batch and loop again to try a smaller payload.
                        if len(current_batch_names) > 1:
                            print(f"    [!] JSON decode failed for large batch. Removing last chunk and retrying...")
                            current_batch_names.pop()
                            current_batch_texts.pop()
                        else:
                            # A single isolated page still failed JSON parsing. We process it using the non-strict fallback.
                            print(f"    [!] Single chunk '{batch_label}' failed JSON parsing. Using text fallback.")
                            page_result = map_extract_chunk(table_result, batch_label, batch_text, strict=False)
                            for c in CATEGORIES:
                                merged[c].extend(page_result.get(c, []))
                                
                            success = True
                            pending_chunks = pending_chunks[1:]

        for c in CATEGORIES:
            merged[c] = dedupe_preserve_order(merged[c])

        print(f"    -> Running Combining Stage (final analysis)")
        final_answer = reduce_stage(table_result, merged)

    if not final_answer:
        print(f"    [-] Analysis failed for {base_name} (empty model response).")
        print_token_table(TOKEN_RECORDS, base_name)
        return

    final_answer = strip_stray_hr_lines(final_answer)

    os.makedirs(ANALYSIS_OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(ANALYSIS_OUTPUT_DIR, f"{base_name}_INFER_OUTPUT.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(final_answer)
    print(f"    [✓] Saved: {out_path}")
    print_token_table(TOKEN_RECORDS, base_name)


def main():
    multiprocessing.freeze_support()

    root = sys.argv[1] if len(sys.argv) > 1 else INPUT_MARKDOWNS_DIR

    if not os.path.isdir(root):
        print(f"'{root}' not found (expected a folder of .md/.json pairs).")
        return

    md_files = []
    for r, _dirs, files in os.walk(root):
        for f in files:
            if f.endswith(".md"):
                md_files.append(os.path.join(r, f))
    md_files.sort()

    if not md_files:
        print(f"No Markdown (.md) files found under '{root}'.")
        return

    print(f"Found {len(md_files)} document(s). Starting extraction + analysis...\n")
    print("=" * 65)

    for md_filepath in md_files:
        base_name = os.path.splitext(os.path.basename(md_filepath))[0]
        print(f"\n📂 Analyzing: {base_name}")
        try:
            process_document(md_filepath, base_name)
        except Exception as e:
            print(f"    [-] Unexpected error on {base_name}: {e}")
        print("-" * 65)

    print(f"\n🎉 SUCCESS: All documents analyzed.")
    print(f"⏱  Total inference time across all documents/stages: {GRAND_TOTAL_SECONDS:.2f}s")


if __name__ == "__main__":
    main()