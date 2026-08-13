"""
=========================================================================
USAGE
=========================================================================
Run from the command line, pointing at a directory that contains the
per-document Markdown files produced upstream (typically the output of
CHUNKS_EXTRACTOR.py):

    python INFERENCE_ON_MARKDOWN.py <path_to_markdowns_directory>

Example:

    python INFERENCE_ON_MARKDOWN.py OUTPUT_EXTRACTED_CHUNKS_TXT

What it does:
  - Recursively finds every *.md file under <path_to_markdowns_directory>.
  - For each one, extracts ATC chunks and runs either the SINGLE-SHOT or
    MAP-REDUCE analysis pipeline (see below) against a local llama-server.
  - Writes "<base_name>_INFER_OUTPUT.md" for each document into the
    ANALYSIS_OUTPUT_DIR folder ("OUTPUT" by default, see CONFIG section).

Requirements before running:
  1. A local llama-server instance must already be running and reachable
     at LLAMA_SERVER_URL (default: http://localhost:8080), exposing the
     OpenAI-compatible /v1/chat/completions endpoint.
  2. The model actually being served by llama-server should match
     QWEN_TOKENIZER_NAME (default: "Qwen/Qwen3-4B"), since that tokenizer
     is used locally purely for token-budgeting/context-window math.
  3. Mineru_Document_To_Markdown.py (providing safe_convert_docx_to_md)
     must be importable from the same environment/directory.
  4. Python dependencies (requests, transformers, beautifulsoup4,
     pymupdf, tabulate) are auto-installed on first run if missing, but
     an internet connection / package index access is needed for that.

Key CONFIG values you may want to adjust before running (see CONFIG
section below): ANALYSIS_OUTPUT_DIR, LLAMA_SERVER_URL, CONTEXT_WINDOW,
QWEN_TOKENIZER_NAME.

=========================================================================
ANALYZE_CHUNKS.py
------------------
Consumes the per-document chunk folders produced by CHUNKS_EXTRACTOR.py
(under OUTPUT_EXTRACTED_CHUNKS_TXT/<base_name>/...) and runs the final
procurement-analysis prompt against the local llama-server.

Two modes, chosen automatically per document folder:

  SINGLE-SHOT  -> only one ATC chunk exists (markdown-only case, no PDF).
                  The full analysis prompt is run once, directly.

  MAP-REDUCE   -> multiple page chunks exist (PDF case, or long Markdown case).
                  Stage 1 (MAP):    The original embedded Markdown chunk is processed 
                                    first as a standalone using maximum context. Remaining downloaded chunks 
                                    (DOCX chunks and PDF pages) are processed using a 
                                    dynamic self-healing queue with a 50-50 split limit. 
                                    If the model breaks JSON format, the batch shrinks by 1 chunk, pushes the removed chunk 
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
import time
import multiprocessing
import tempfile

# --- Auto-install deps ---
def install_and_import(package, import_name):
    """Ensure a third-party package is available before it is imported.

    Tries to import `import_name` (the name used in `import` statements,
    e.g. "bs4"). If that fails, pip-installs `package` (the PyPI
    distribution name, e.g. "beautifulsoup4") using the current
    interpreter, so the rest of the script can import it unconditionally
    right after this call.
    """
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

from Mineru_Document_To_Markdown import safe_convert_docx_to_md

# =========================================================================
# CONFIG
# =========================================================================
ANALYSIS_OUTPUT_DIR = "OUTPUT"                   # where final .md analyses are written
LLAMA_SERVER_URL = "http://localhost:8080"       # base URL of the local llama-server instance
CHAT_ENDPOINT = f"{LLAMA_SERVER_URL}/v1/chat/completions"  # OpenAI-compatible chat completions endpoint

CONTEXT_WINDOW = 9216  # total context window (in tokens) the served model supports

# The tokenizer must match the model actually being served by llama-server
QWEN_TOKENIZER_NAME = "Qwen/Qwen3-4B"

# Reserve tokens for chat-template overhead
TEMPLATE_OVERHEAD_TOKENS = 100  # buffer subtracted from CONTEXT_WINDOW to account for chat-template formatting tokens

# 50-50 Split for Map Stage (Chunking)
# During the MAP stage, the remaining context budget (after overhead) is split
# evenly between how much input text a batch may contain and how much output
# JSON the model is allowed to generate for that batch.
CHUNK_CATEGORIZING_MAX_OUTPUT_TOKENS = int((CONTEXT_WINDOW - TEMPLATE_OVERHEAD_TOKENS) * 0.5)
CHUNK_CATEGORIZING_MAX_INPUT_TOKENS = int((CONTEXT_WINDOW - TEMPLATE_OVERHEAD_TOKENS) * 0.5)

# Output caps for Final Stage
FINAL_STAGE_OUTPUT_TOKENS = 2000      # max tokens the model may generate for the final analysis answer
FINAL_STAGE_INPUT_TOKENS = CONTEXT_WINDOW - FINAL_STAGE_OUTPUT_TOKENS - TEMPLATE_OVERHEAD_TOKENS  # remaining budget for the final-stage prompt

# =========================================================================
# EXTRACTION-STAGE CONFIG
# =========================================================================
REQUIRED_DOCS_HEADER = "Document required from seller"  # label used to locate the "required docs" table row in the source markdown
ATC_SECTION_START_MARKER = "Buyer Added Bid Specific Terms and Conditions"  # marks the start of the embedded ATC text block
ATC_SECTION_END_MARKER = "अस्वीकरण/Disclaimer"  # marks the end of the embedded ATC text block
ATC_PDF_LINK_NAME = "Buyer uploaded ATC document"  # hyperlink display-name used to find the downloadable ATC file (PDF/DOCX)

# The five evidence/requirement buckets used throughout the MAP and REDUCE stages
CATEGORIES = [
    "STANDARD_DOCS",
    "ATC_PLACEHOLDER_CLARIFICATION",
    "EXEMPTION",
    "PHYSICAL_SUBMISSION",
    "COMMERCIAL_TERMS",
]

print(f"Loading tokenizer for {QWEN_TOKENIZER_NAME} (used for context-window budgeting)...")
_enc = AutoTokenizer.from_pretrained(QWEN_TOKENIZER_NAME, trust_remote_code=True)  # module-level tokenizer used only for token counting/budgeting


def count_tokens(text: str) -> int:
    """Return the number of tokens `text` would occupy per the loaded tokenizer.

    Used everywhere in this script to budget prompts against CONTEXT_WINDOW.
    Returns 0 for empty/falsy input instead of erroring.
    """
    if not text:
        return 0
    return len(_enc.encode(text, add_special_tokens=False))


# =========================================================================
# PROGRESS SPINNER
# =========================================================================
def _run_spinner(description, stop_event):
    """Worker function (run in a separate process) that repeatedly redraws a
    spinner + elapsed-time line on stdout until `stop_event` is set.

    description: label text shown next to the spinner (truncated to 70 chars).
    stop_event:  multiprocessing.Event used by the parent process to signal
                 the spinner loop to stop.
    """
    start_time = time.time()  # when this spinner process started, for elapsed-time display
    spinner = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']  # braille frames cycled to animate the spinner
    idx = 0  # current frame index into `spinner`
    
    if len(description) > 70:
        description = description[:67] + "..."
        
    while not stop_event.is_set():
        elapsed = time.time() - start_time
        sys.stdout.write(f"\r\033[2K{spinner[idx]} {description} | Elapsed time: {elapsed:.1f}s")
        sys.stdout.flush()
        idx = (idx + 1) % len(spinner)
        time.sleep(0.1)


class ProgressTimer:
    """Displays an animated CLI spinner (in a background process) for the
    duration of a long-running operation (e.g. an LLM call), then replaces
    it with a "completed in Xs" line once stopped.
    """

    def __init__(self, description):
        self.description = description          # label shown next to the spinner/checkmark
        self._stop_event = multiprocessing.Event()  # signals the spinner subprocess to stop
        self._process = None                     # holds the spinner subprocess once started
        self.start_time = None                   # timestamp set in start(), used to compute total elapsed time

    def start(self):
        """Record the start time and launch the spinner in a daemon subprocess."""
        self.start_time = time.time()
        self._process = multiprocessing.Process(target=_run_spinner, args=(self.description, self._stop_event))
        self._process.daemon = True
        self._process.start()

    def stop(self):
        """Signal the spinner subprocess to stop, wait for it to exit, then
        print a final checkmark line with the total elapsed time."""
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
TOKEN_RECORDS = []          # list of (label, input_tokens, output_tokens, elapsed_seconds) tuples for the CURRENT document; reset per document in process_document()
GRAND_TOTAL_SECONDS = 0.0   # running total of LLM call time across ALL documents processed in this run


def record_call(label: str, system_prompt: str, user_prompt: str, output_text: str,
                 elapsed_seconds: float) -> None:
    """Log the token usage and timing of one LLM call into TOKEN_RECORDS and
    accumulate its duration into GRAND_TOTAL_SECONDS.

    label:            short stage name shown in the usage table (e.g. "MAP: <chunk>").
    system_prompt:    the system prompt sent for this call (counted as input tokens).
    user_prompt:       the user prompt sent for this call (counted as input tokens).
    output_text:      the text the model returned (counted as output tokens).
    elapsed_seconds:  wall-clock duration of the call.
    """
    global GRAND_TOTAL_SECONDS
    in_tokens = count_tokens(system_prompt) + count_tokens(user_prompt)
    out_tokens = count_tokens(output_text)
    TOKEN_RECORDS.append((label, in_tokens, out_tokens, elapsed_seconds))
    GRAND_TOTAL_SECONDS += elapsed_seconds


def print_token_table(records, title: str) -> None:
    """Pretty-print a per-stage token/timing usage table (plus a TOTAL row)
    for one document, using `tabulate`. No-ops if `records` is empty.

    records: list of (label, input_tokens, output_tokens, elapsed_seconds) tuples.
    title:   heading shown above the table (typically the document's base name).
    """
    if not records:
        return

    headers = ["Stage", "Input Tokens", "Output Tokens", "Time (s)"]
    rows = [(label, str(i), str(o), f"{t:.2f}") for label, i, o, t in records]
    
    total_in = sum(i for _, i, _, _ in records)
    total_out = sum(o for _, _, o, _ in records)
    total_time = sum(t for _, _, _, t in records)
    rows.append(("TOTAL", str(total_in), str(total_out), f"{total_time:.2f}"))

    print(f"\n    Token Usage — {title}")
    
    table_str = tabulate(rows, headers=headers, tablefmt="fancy_grid", maxcolwidths=[60, None, None, None])
    
    for line in table_str.splitlines():
        print(f"    {line}")
    print()


# =========================================================================
# LLAMA-SERVER CALL
# =========================================================================
def call_llm(system_prompt: str, user_prompt: str, max_tokens: int,
             frequency_penalty: float = 0.0, seed: int = 42, require_json: bool = False) -> str:
    """Send a single chat-completion request to the local llama-server and
    return the model's reply text (stripped).

    system_prompt:     content of the system message.
    user_prompt:        content of the user message.
    max_tokens:        generation cap for this call.
    frequency_penalty: passed through to the server; higher = less repetition.
    seed:              fixed sampling seed for reproducibility.
    require_json:      if True, asks the server to constrain output to a JSON object
                        via response_format.

    Returns the response text, or "" if the request fails for any reason
    (network error, non-2xx status, malformed response body, etc.).
    """
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


def timed_llm_call(spinner_label: str, record_label: str, system_prompt: str, user_prompt: str,
                    max_tokens: int, frequency_penalty: float = 0.0, require_json: bool = False) -> str:
    """Runs call_llm() wrapped in a ProgressTimer, then logs it via record_call().
    Centralizes the timer/call/record pattern shared by map_extract_chunk,
    compress_category, reduce_stage, and single_shot_stage."""
    _t0 = time.time()
    timer = ProgressTimer(spinner_label)
    timer.start()
    result = call_llm(system_prompt, user_prompt, max_tokens=max_tokens,
                       frequency_penalty=frequency_penalty, require_json=require_json)
    timer.stop()
    record_call(record_label, system_prompt, user_prompt, result, time.time() - _t0)
    return result


# =========================================================================
# PROMPTS
# =========================================================================
# ANALYSIS_SYSTEM_PROMPT: the final "produce the checklist" prompt, used by
# both SINGLE-SHOT mode and the end of MAP-REDUCE mode (Stage 2).
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


# MAP_SYSTEM_PROMPT: used per-chunk/per-batch in the MAP stage to pull raw
# evidence sentences (verbatim) into the five CATEGORIES buckets, without
# summarizing or interpreting. `{table_result}` is filled in via .format().
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

# COMPRESS_SYSTEM_PROMPT: used in the REDUCE-stage safety fallback to
# de-duplicate/shrink one oversized evidence category (`{category}`) when the
# merged evidence text doesn't fit the final-stage context budget.
COMPRESS_SYSTEM_PROMPT = """You are merging duplicate/overlapping evidence sentences that were extracted from different pages of the same tender document, for a single category: {category}.
Remove exact or near-exact duplicates (e.g. repeated boilerplate/headers). Keep every distinct fact, deadline, name, amount, or condition. Do not summarize away specifics or invent anything not present in the input. Output ONE sentence per line, plain text, no numbering, no commentary."""


# =========================================================================
# IN-MEMORY CHUNK EXTRACTION
# =========================================================================
def extract_table_value(filepath: str, search_key: str) -> str:
    """Find an HTML `<table>` row (two `<td>` cells) in the markdown/HTML file
    at `filepath` whose first cell matches `search_key` (case-insensitive
    substring match) and return it formatted as "key : value".

    Used to pull the "Document required from seller" row out of the source
    markdown. Returns an "Error: ..." / "not found" string instead of raising
    if the file is missing or the key isn't present.
    """
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
    """Return the substring of the file at `filepath` that lies strictly
    between the first occurrence of `start_marker` and the following
    occurrence of `end_marker` (both markers excluded, result stripped).

    Used to pull the embedded ATC (Additional Terms and Conditions) text out
    of the source markdown between ATC_SECTION_START_MARKER and
    ATC_SECTION_END_MARKER. Returns an "Error: ..." string (rather than
    raising) if the file, start marker, or end marker isn't found.
    """
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
    """
    Validates and returns file bytes for PDF or DOCX formats. 
    Checks the full URL string to support query parameters.
    Throws a hard error and exits instantly if any other format is detected.
    Returns: (bytes, file_type_string)
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, timeout=15, headers=headers)
        resp.raise_for_status()

        if "login" in resp.url.lower():
            print(f"\n    [-] Skipped: Redirected to login page -> {url}")
            return None, None

        content_type = resp.headers.get("Content-Type", "").lower()
        if "text/html" in content_type:
            print(f"\n    [-] Skipped: URL requires authentication -> {url}")
            return None, None

        url_lower = url.lower()
        
        is_pdf = "pdf" in content_type or ".pdf" in url_lower
        is_docx = "wordprocessingml.document" in content_type or ".docx" in url_lower

        if is_pdf:
            return resp.content, "pdf"
        elif is_docx:
            return resp.content, "docx"
        else:
            print(f"\n\n    [FATAL ERROR] Unsupported file type detected.")
            print(f"    URL: {url}")
            print(f"    Content-Type: '{content_type}'")
            print("    Only PDF or DOCX external files are supported. Terminating execution.")
            os._exit(1)

    except Exception as e:
        print(f"\n\n    [FATAL ERROR] Failed to download ATC document: {e}")
        print("    Terminating execution.")
        os._exit(1)


def extract_pdf_pages_in_memory(pdf_bytes: bytes, base_name: str):
    """Open a PDF (given as raw bytes) with pymupdf and return a list of
    (chunk_name, page_text) tuples, one per page, named
    "<base_name>_ATC_PDF_CHUNK_<page_number>" (1-indexed).

    Returns an empty list (and logs the error) if the PDF fails to open/parse.
    """
    chunks = []
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        for page_num in range(1, len(doc) + 1):
            page_text = doc.load_page(page_num - 1).get_text("text").strip()
            chunks.append((f"{base_name}_ATC_PDF_CHUNK_{page_num}", page_text))
        doc.close()
    except Exception as e:
        print(f"    [-] Error extracting text from PDF: {e}")
    return chunks


def extract_document_chunks_in_memory(md_filepath: str):
    """Build the full list of ATC text "chunks" for one source document,
    entirely in memory (no intermediate files written to disk except a
    short-lived temp file for DOCX conversion).

    Steps:
      1. Pull the "Document required from seller" table row (`table_result`).
      2. Pull the embedded ATC markdown block between the start/end markers
         and strip the "click here to view the file" link boilerplate; if
         present, this becomes the "<base_name>_ATC_MARKDOWN_CHUNK".
      3. Look for a sibling "<base_name>.json" file listing hyperlinks; if it
         contains a link named like ATC_PDF_LINK_NAME, download that file and
         split it into per-page chunks (PDF via extract_pdf_pages_in_memory,
         or DOCX via safe_convert_docx_to_md with page breaks).
      4. If no chunks were produced at all, fall back to a single placeholder
         chunk containing "No Valid ATC Found".

    Returns (table_result, chunks) where chunks is a list of
    (chunk_name, chunk_text) tuples.
    """
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
        # Original embedded Markdown is preserved as a single, unbatched chunk
        chunks.append((f"{base_name}_ATC_MARKDOWN_CHUNK", md_chunk_result))

    json_filepath = os.path.join(os.path.dirname(md_filepath), f"{base_name}.json")
    downloaded_bytes = None  # raw bytes of the downloaded ATC PDF/DOCX, if any is found
    file_type = None         # "pdf" or "docx", set alongside downloaded_bytes

    if os.path.exists(json_filepath):
        try:
            with open(json_filepath, "r", encoding="utf-8") as jf:
                data = json.load(jf)
            for link in data.get("hyperlinks", []):
                name = link.get("name", "")
                url = link.get("url")
                if ATC_PDF_LINK_NAME.lower() in name.lower() and url:
                    downloaded_bytes, file_type = download_pdf_bytes(url)
                    break
        except json.JSONDecodeError:
            print(f"    [-] Error: Failed to parse JSON in {json_filepath}")
        except Exception as e:
            print(f"    [-] Unexpected error processing JSON: {e}")
    else:
        print(f"    [-] No corresponding JSON file found at {json_filepath}")

    if downloaded_bytes:
        if file_type == "pdf":
            chunks.extend(extract_pdf_pages_in_memory(downloaded_bytes, base_name))
        
        elif file_type == "docx":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                tmp.write(downloaded_bytes)
                tmp_path = tmp.name
            
            try:
                print(f"    -> Converting downloaded DOCX to Markdown (Page Break Mode)...")
                # Utilize page_break=True in Zero Save Mode to get a list of per-page dicts.
                # tmp_path is the temp .docx file written just above from downloaded_bytes.
                page_results = safe_convert_docx_to_md(
                    input_path=tmp_path,
                    output_dir=None,
                    format="gfm",
                    page_break=True
                )
                
                if page_results:
                    for idx, page_info in enumerate(page_results):
                        # Extract the markdown string from the dictionary
                        page_text = page_info.get("markdown", "")
                        if page_text.strip():
                            chunks.append((f"{base_name}_DOWNLOADED_DOCX_PAGE_{idx+1}", page_text.strip()))
                            
            except Exception as e:
                print(f"    [-] Error during DOCX to Markdown conversion: {e}")
            finally:
                os.remove(tmp_path) 

    if not chunks:
        chunks.append((f"{base_name}_ATC_CHUNK_1", "No Valid ATC Found"))

    return table_result, chunks


# =========================================================================
# MAP STAGE
# =========================================================================
def map_extract_chunk(table_result: str, chunk_label: str, atc_text: str, strict: bool = False, use_full_context: bool = False) -> dict:
    """Run one MAP-stage LLM call: extract raw evidence sentences from
    `atc_text` (one chunk, or a batch of concatenated chunks) into the five
    CATEGORIES buckets, truncating the input if needed to fit the token
    budget and requesting strict JSON output from the model.

    table_result:     the "Document required from seller" text, included in the
                       system prompt as reference context.
    chunk_label:       human-readable label for this chunk/batch, used in logs
                       and in the progress spinner/token-usage record.
    atc_text:          the ATC text to extract evidence from (may be truncated).
    strict:            if True, a failure to produce valid JSON raises ValueError
                       instead of falling back to a text blob (used by the
                       self-healing batch queue so it can detect and shrink
                       failing batches).
    use_full_context:  if True, allow this call to use nearly the entire
                       CONTEXT_WINDOW for input (used for the standalone
                       embedded-Markdown chunk, or a single oversized chunk in
                       single_shot_stage) instead of the standard 50/50 split.

    Returns a dict with one list per CATEGORIES key. On a non-strict JSON
    parse failure, returns a fallback dict with the raw, truncated model
    output stashed under COMMERCIAL_TERMS so the evidence isn't silently lost.
    """
    empty = {c: [] for c in CATEGORIES}

    system_prompt = MAP_SYSTEM_PROMPT.format(table_result=table_result)
    budget_check = count_tokens(system_prompt) + count_tokens(atc_text)

    # Determine limits based on the stage
    if use_full_context:
        # Use as much context as possible for input, keeping at least a 1000 token safety buffer for output
        input_limit = CONTEXT_WINDOW - TEMPLATE_OVERHEAD_TOKENS - 1000
    else:
        input_limit = CHUNK_CATEGORIZING_MAX_INPUT_TOKENS

    if budget_check > input_limit:
        allowed_chars = int(len(atc_text) * (input_limit / budget_check) * 0.95)
        atc_text = atc_text[:allowed_chars]
        print(f"    [!] {chunk_label}: text truncated to fit {input_limit} token budget")
        budget_check = count_tokens(system_prompt) + count_tokens(atc_text) # Recalculate after truncate

    # Dynamically calculate output limit based on actual input usage
    if use_full_context:
        output_limit = CONTEXT_WINDOW - TEMPLATE_OVERHEAD_TOKENS - budget_check
    else:
        output_limit = CHUNK_CATEGORIZING_MAX_OUTPUT_TOKENS

    raw = timed_llm_call(f"Processing {chunk_label} (MAP stage, llama.cpp)", f"MAP: {chunk_label}",
                         system_prompt, atc_text, max_tokens=output_limit, require_json=True)
    
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
        if strict:
            raise ValueError("Invalid JSON format from model")
            
        print(f"    [!] {chunk_label}: map-stage output wasn't valid JSON, keeping raw text as fallback evidence")
        fallback = empty
        fallback["COMMERCIAL_TERMS"] = [f"[UNPARSED PAGE OUTPUT - {chunk_label}] {raw_clean[:1500]}"]
        return fallback


def dedupe_preserve_order(items):
    """Remove near-duplicate strings from `items` while preserving the order
    of first occurrence. Two items are considered duplicates if they're equal
    after lowercasing and collapsing internal whitespace; empty items are
    dropped. Returns a new list of the (whitespace-trimmed) original strings.
    """
    seen = set()   # normalized (whitespace-collapsed, lowercased) keys already emitted
    out = []
    for it in items:
        key = re.sub(r"\s+", " ", it.strip().lower())
        if key and key not in seen:
            seen.add(key)
            out.append(it.strip())
    return out


def strip_stray_hr_lines(text: str) -> str:
    """Post-process the final analysis text: remove any line that consists
    solely of a Markdown horizontal-rule (---, ***, or ___, 3+ repeats,
    optionally padded with whitespace) and collapse 3+ consecutive blank
    lines down to a single blank line. Returns the trimmed result, or `text`
    unchanged if it's falsy.
    """
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
    """REDUCE-stage safety fallback: ask the model to de-duplicate/merge the
    evidence sentences in `lines` for a single `category`, to shrink an
    oversized evidence bucket so the final analysis prompt fits its token
    budget. Returns the compressed list of sentences (one per output line,
    leading "- "/"-" markers stripped), or the original `lines` unchanged if
    the model call returns nothing.
    """
    joined = "\n".join(lines)
    system_prompt = COMPRESS_SYSTEM_PROMPT.format(category=category)
    out = timed_llm_call(f"Compressing category '{category}' (llama.cpp)", f"COMPRESS: {category}",
                         system_prompt, joined, max_tokens=CHUNK_CATEGORIZING_MAX_OUTPUT_TOKENS)
    if not out:
        return lines
    return [l.strip("- ").strip() for l in out.splitlines() if l.strip()]


def build_reduced_evidence_text(merged: dict) -> str:
    """Render the merged per-category evidence dict (CATEGORIES -> list of
    sentences) into a single flat text block, with a "[CATEGORY]" header and
    "- sentence" bullet lines per category (or "- (none found)" if a category
    is empty). This is the text fed as the ATC section of the final analysis
    prompt in place of raw ATC text.
    """
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
    """REDUCE stage: turn the merged/deduped per-category evidence (`merged`,
    produced by one or more map_extract_chunk calls) into the final
    structured analysis, by running ANALYSIS_SYSTEM_PROMPT once against the
    compacted evidence text instead of raw ATC text.

    If the compacted evidence + prompts don't fit FINAL_STAGE_INPUT_TOKENS,
    iteratively compresses (via compress_category) the single largest
    category (by total character length) and rebuilds the evidence text, up
    to 3 attempts, before giving up and sending whatever fits.

    Returns the final analysis text produced by the model (may be empty on
    failure).
    """
    evidence_text = build_reduced_evidence_text(merged)
    budget_check = count_tokens(ANALYSIS_SYSTEM_PROMPT) + count_tokens(table_result) + count_tokens(evidence_text)

    attempts = 0
    while budget_check > FINAL_STAGE_INPUT_TOKENS and attempts < 3:
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

    result = timed_llm_call("Running Combining Stage - final analysis (llama.cpp)", "Combining Stage",
                            ANALYSIS_SYSTEM_PROMPT, user_prompt, max_tokens=FINAL_STAGE_OUTPUT_TOKENS,
                            frequency_penalty=1.0)
    return result


# =========================================================================
# SINGLE-SHOT 
# =========================================================================
def single_shot_stage(table_result: str, atc_text: str) -> str:
    """SINGLE-SHOT mode: used when a document has exactly one ATC chunk.
    Runs ANALYSIS_SYSTEM_PROMPT once directly against the raw `atc_text`.

    If the combined prompt is too large for FINAL_STAGE_INPUT_TOKENS, falls
    back to routing this single chunk through the MAP/REDUCE pipeline instead
    (map_extract_chunk with the full context window, then reduce_stage) so
    oversized single-chunk documents are still handled safely.

    Returns the final analysis text.
    """
    total = count_tokens(ANALYSIS_SYSTEM_PROMPT) + count_tokens(table_result) + count_tokens(atc_text)
    if total > FINAL_STAGE_INPUT_TOKENS:
        print(f"    [!] Single chunk is large (~{total} tokens) - routing through map/reduce instead of one-shot")
        merged = map_extract_chunk(table_result, "single_chunk", atc_text, use_full_context=True)
        for c in CATEGORIES:
            merged[c] = dedupe_preserve_order(merged[c])
        return reduce_stage(table_result, merged)

    user_prompt = (
        f"Document required from seller:\n{table_result}\n\n"
        f"======\n\n"
        f"Additional Terms and Conditions:\n{atc_text}\n"
    )
    result = timed_llm_call("Running SINGLE-SHOT analysis (llama.cpp)", "SINGLE-SHOT (final)",
                            ANALYSIS_SYSTEM_PROMPT, user_prompt, max_tokens=FINAL_STAGE_OUTPUT_TOKENS,
                            frequency_penalty=1.0)
    return result


# =========================================================================
# MAIN
# =========================================================================
def process_document(md_filepath: str, base_name: str):
    """End-to-end pipeline for a single source markdown document:
      1. Extract in-memory ATC chunks (extract_document_chunks_in_memory).
      2. Choose SINGLE-SHOT (one chunk) or MAP-REDUCE (multiple chunks) mode.
         In MAP-REDUCE mode: run the embedded markdown chunk standalone first
         (full context), then process any downloaded PDF/DOCX chunks through
         a dynamic self-healing batching queue (shrinks a batch by one chunk
         and retries on JSON failure, falling back to non-strict parsing for
         a lone chunk that still fails), then merge + dedupe + reduce.
      3. Write the final answer to "<ANALYSIS_OUTPUT_DIR>/<base_name>_INFER_OUTPUT.md".
      4. Print a per-document token/timing usage table.

    Any failure to produce a final answer (empty model response) is logged
    and the function returns without writing an output file.
    """
    TOKEN_RECORDS.clear()

    timer = ProgressTimer(f"Generating chunks for {base_name}")
    timer.start()
    table_result, chunks = extract_document_chunks_in_memory(md_filepath)
    timer.stop()

    chunks = [(name, atc) for name, atc in chunks if atc]  # drop any chunks with empty extracted text

    if not chunks:
        print(f"    [-] No usable chunk text found in {md_filepath}, skipping.")
        return

    if len(chunks) == 1:
        print(f"    -> Single chunk detected ({chunks[0][0]}): running one-shot analysis")
        final_answer = single_shot_stage(table_result, chunks[0][1])
    else:
        print(f"    -> {len(chunks)} chunks detected. Processing Markdown first, then batching external documents.")
        merged = {c: [] for c in CATEGORIES}
        
        # 1. Separate original embedded Markdown chunk from external downloaded chunks
        md_chunk = next((c for c in chunks if "ATC_MARKDOWN_CHUNK" in c[0]), None)
        downloaded_chunks = [c for c in chunks if "ATC_MARKDOWN_CHUNK" not in c[0]]
        
        # 2. Run original Markdown chunk alone first (if it exists)
        if md_chunk:
            print(f"    -> Isolating explicit terms. Running standalone MAP stage for: {md_chunk[0]}")
            # Use the full context window for the initial markdown run
            md_result = map_extract_chunk(table_result, md_chunk[0], md_chunk[1], strict=False, use_full_context=True)
            for c in CATEGORIES:
                merged[c].extend(md_result.get(c, []))
        
        # 3. Dynamic Self-Healing Queue for the remaining downloaded chunks (PDF or DOCX)
        if downloaded_chunks:
            base_prompt_tokens = count_tokens(MAP_SYSTEM_PROMPT.format(table_result=table_result))  # fixed system-prompt overhead shared by every batch
            pending_chunks = downloaded_chunks.copy()  # chunks still waiting to be processed; shrinks as batches succeed
            
            while pending_chunks:
                # --- Greedily build the next batch, filling up to the input token budget ---
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
                
                # --- Try the batch, shrinking it by one chunk each time JSON parsing fails ---
                success = False
                while current_batch_names and not success:
                    batch_label = " + ".join(current_batch_names)
                    batch_text = "".join(current_batch_texts)
                    
                    try:
                        page_result = map_extract_chunk(table_result, batch_label, batch_text, strict=True)
                        for c in CATEGORIES:
                            merged[c].extend(page_result.get(c, []))
                            
                        success = True
                        pending_chunks = pending_chunks[len(current_batch_names):]
                        
                    except ValueError:
                        if len(current_batch_names) > 1:
                            print(f"    [!] JSON decode failed for large batch. Removing last chunk and retrying...")
                            current_batch_names.pop()
                            current_batch_texts.pop()
                        else:
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
    """CLI entry point: recursively find every .md file under the directory
    passed as argv[1], run process_document() on each one (catching and
    logging any per-document exception so one failure doesn't abort the
    batch), then print a final summary with total inference time.
    """
    multiprocessing.freeze_support()  # required on Windows/frozen builds for the spinner subprocess

    if len(sys.argv) < 2:
        print("Usage: python ANALYZE_CHUNKS.py <path_to_markdowns_directory>")
        sys.exit(1)

    root = sys.argv[1]  # root directory to search for .md files

    if not os.path.isdir(root):
        print(f"'{root}' not found (expected a folder of .md/.json pairs).")
        return

    md_files = []  # collected paths of every .md file found under root
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