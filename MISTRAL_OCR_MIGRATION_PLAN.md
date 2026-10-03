# 🗺️ Implementation Plan — Mistral OCR Migration (v2)

> **Branch:** `development_v2`
> **Goal:** Replace Mineru VLM (GPU-heavy, local vLLM server) with Mistral OCR API (`mistral-ocr-latest`) for PDF → Markdown conversion.
> **Scope:** Only the OCR layer changes. Everything else (browser, parser, RAG, DB, scheduler) stays identical.

---

## 🔍 What Exactly Changes vs. Stays the Same

### ❌ Goes Away (Mineru-specific)
| What | Where in code |
|------|--------------|
| `from Mineru_Document_To_Markdown import async_convert_document, set_vlm_config, async_start_vllm_server, close_vllm_server` | `pipeline/scraper.py` L29-34 |
| `AsyncWorker` class (background asyncio loop for Mineru) | `pipeline/scraper.py` L128-183 |
| vLLM server startup block (`async_start_vllm_server`) | `scrape_specific_bid()` L541-549 and `run_full_scrape()` L613-623 |
| vLLM server shutdown block (`close_vllm_server`) | both functions finally-blocks |
| `set_vlm_config(batch_size=16, max_gpu_util=0.78, model_len=4096)` | both functions |
| `suppress_stdout_stderr()` context manager (only needed for noisy vLLM) | `pipeline/scraper.py` L107-125 |
| `os.environ["MINERU_LOG_LEVEL"]` / `VLLM_LOGGING_LEVEL` | `pipeline/scraper.py` L26-27 |
| `worker` parameter passed into `process_card_item()` | function signature + callers |
| `Mineru_Document_To_Markdown` in `requirements.txt` | `requirements.txt` |
| `vllm`, `flash-attn` (GPU inference deps) | `requirements.txt` |

### ✅ Stays Identical
- `core/browser.py` — Playwright scraper
- `core/parser.py` — Markdown structured field parser
- `utils/pdf_hyperlinks.py` — PyMuPDF link extraction
- `storage/database.py` — SQLite ORM
- `rag/` — all 4 RAG modules (embedder, vector_store, query_engine, llm)
- `pipeline/scheduler.py` — hourly loop
- `main.py` — CLI dispatcher
- `ATC EXTRACTOR/` — untouched

---

## 🏗️ Architecture Comparison

```
── CURRENT (Mineru / v1) ────────────────────────────────────────────
PDF path
  → [AsyncWorker + vLLM server running locally on GPU]
  → async_convert_document(input_path, backend="vlm-engine")
  → {"markdown": "..."} (in-memory dict)
  → pdf_text string

── TARGET (Mistral OCR / v2) ────────────────────────────────────────
PDF path
  → [Mistral API call — no GPU, no local server]
  → client.files.upload(pdf_bytes)          # upload to Mistral
  → client.files.get_signed_url(file_id)   # get temporary signed URL
  → client.ocr.process(model="mistral-ocr-latest", document_url=...)
  → join([page.markdown for page in response.pages])
  → pdf_text string
```

The output contract (`pdf_text` string) is **identical** — everything downstream is untouched.

---

## 📋 Phase-by-Phase Plan

---

### Phase 1 — New OCR Abstraction Module

**Create: `core/ocr.py`**

A thin provider-switching wrapper. This is the ONLY new file.

```
core/
  browser.py    (existing)
  parser.py     (existing)
  ocr.py        <- NEW
  __init__.py   (existing)
```

**What it contains:**

```python
# core/ocr.py
# OCR Provider abstraction — supports "mistral" (and "mineru" as legacy)

def convert_pdf_to_markdown(pdf_path: str) -> str:
    """
    Convert a PDF file to Markdown using the configured OCR provider.
    Returns a markdown string (empty string on failure).

    Provider is selected via OCR_PROVIDER in .env:
      - "mistral"  -> Mistral OCR API (mistral-ocr-latest)
    """
    from config.settings import OCR_PROVIDER
    if OCR_PROVIDER == "mistral":
        return _mistral_ocr(pdf_path)
    else:
        raise ValueError(f"Unknown OCR_PROVIDER: '{OCR_PROVIDER}'")


def _mistral_ocr(pdf_path: str) -> str:
    """
    Upload PDF to Mistral, run mistral-ocr-latest, return joined markdown.

    Steps:
      1. Read PDF bytes from disk
      2. Upload to Mistral Files API (purpose="ocr")
      3. Get signed URL for the uploaded file
      4. Call client.ocr.process() with the signed URL
      5. Join all page.markdown strings
      6. Delete the uploaded file from Mistral (cleanup)
    """
    ...
```

**Key design decisions:**
- **Synchronous** — no asyncio needed (Mistral SDK is sync). This removes the entire `AsyncWorker` complexity.
- **File cleanup** — uploaded PDF deleted from Mistral after OCR to avoid storage quota creep.
- **Error handling** — on any API failure, log and return `""` (same as current Mineru failure path).
- **Retry** — 3 attempts with 5s backoff for transient 5xx errors.

---

### Phase 2 — Config Changes

**File: `config/settings.py`** — add 2 new keys:

```python
# OCR Provider: "mistral"
OCR_PROVIDER    = _str("OCR_PROVIDER", "mistral")
MISTRAL_API_KEY = _str("MISTRAL_API_KEY", "")
```

**File: `.env.example`** — add new section:

```ini
# ---------------------------------------------------------
# OCR PROVIDER
# Options: mistral
# ---------------------------------------------------------
OCR_PROVIDER=mistral
MISTRAL_API_KEY=your_mistral_api_key_here
```

**Your `.env`** — add:
```ini
OCR_PROVIDER=mistral
MISTRAL_API_KEY=<your key from https://console.mistral.ai>
```

---

### Phase 3 — Scraper Refactor

**File: `pipeline/scraper.py`** — this is the biggest change but mostly *deletion*.

#### 3a. Remove Mineru imports (top of file)
```python
# REMOVE these lines:
os.environ["MINERU_LOG_LEVEL"] = "WARNING"
os.environ["VLLM_LOGGING_LEVEL"] = "WARNING"
from Mineru_Document_To_Markdown import (
    async_convert_document, set_vlm_config,
    async_start_vllm_server, close_vllm_server,
)
import asyncio
import threading

# ADD this 1 line:
from core.ocr import convert_pdf_to_markdown
```

#### 3b. Remove `AsyncWorker` class entirely (L128-183)
~55 lines of boilerplate gone.

#### 3c. Remove `suppress_stdout_stderr()` context manager (L107-125)
No longer needed — Mistral API calls produce no noisy stdout.

#### 3d. Update `process_card_item()` signature
```python
# BEFORE:
def process_card_item(card, browser, db, worker, bid_type_name, ...):

# AFTER:
def process_card_item(card, browser, db, bid_type_name, ...):
```

#### 3e. Replace the Mineru conversion block (Step 6)
```python
# BEFORE (15 lines — Mineru):
conv_timer = ProgressTimer(f"Converting PDF ({safe_bid_no}) to Markdown Via Mineru VLLM Server")
conv_timer.start()
try:
    with suppress_stdout_stderr():
        conv_result = worker.run(async_convert_document(...))
        if isinstance(conv_result, dict):
            pdf_text = conv_result.get("markdown", "")
except Exception as e:
    log.error(f"Mineru VLM conversion failed for {safe_bid_no}: {e}")
finally:
    conv_timer.stop()

# AFTER (6 lines — Mistral):
conv_timer = ProgressTimer(f"Converting PDF ({safe_bid_no}) to Markdown Via Mistral OCR")
conv_timer.start()
try:
    pdf_text = convert_pdf_to_markdown(pdf_path)
except Exception as e:
    log.error(f"Mistral OCR conversion failed for {safe_bid_no}: {e}")
finally:
    conv_timer.stop()
```

#### 3f. Remove `worker` from `scrape_bid_type()`
```python
# BEFORE:
def scrape_bid_type(browser, db, worker, bid_type_name, seen_urls):
    ...
    res = process_card_item(..., worker=worker, ...)

# AFTER:
def scrape_bid_type(browser, db, bid_type_name, seen_urls):
    ...
    res = process_card_item(..., bid_type_name=bid_type_name)
```

#### 3g. Gut `scrape_specific_bid()` — remove entire vLLM lifecycle
```
REMOVE: AsyncWorker(), set_vlm_config(), server_timer startup, close_timer shutdown
Function body shrinks from ~65 lines to ~30 lines
```

#### 3h. Gut `run_full_scrape()` — remove entire vLLM lifecycle
```
REMOVE: AsyncWorker(), set_vlm_config(), server_timer startup, close_timer shutdown
scrape_bid_type() call loses the worker= argument
```

---

### Phase 4 — Requirements Update

**File: `requirements.txt`**

```diff
# ADD
+ mistralai>=1.0.0

# REMOVE (OCR-specific GPU deps — no longer needed)
- vllm==0.21.0
- flash-attn @ https://...
- Mineru_Document_To_Markdown[all] @ git+...
- git+https://github.com/ThriveX2025/Mineru_Utils.git

# KEEP (RAG embedder still uses torch for GPU acceleration)
  torch==2.11.0
  sentence-transformers>=3.0.0
```

> **Note:** `torch` stays because `rag/embedder.py` uses it for GPU-accelerated
> sentence embeddings. Only the vLLM / Mineru inference stack is removed.

---

### Phase 5 — Standalone Test Script

**Create: `STANDLONE TEST SCRIPTS/TEST_MISTRAL_OCR.py`**

Validates Mistral OCR output quality against existing scraped PDFs before
wiring into the main pipeline.

```python
# Test Mistral OCR against known bid PDFs
# Run: python "STANDLONE TEST SCRIPTS/TEST_MISTRAL_OCR.py"

from core.ocr import convert_pdf_to_markdown
import os, glob

TEST_PDFS = glob.glob("downloads/**/*.pdf", recursive=True)[:5]

for pdf_path in TEST_PDFS:
    bid_name = os.path.basename(pdf_path)
    print(f"\n{'='*60}")
    print(f"Testing: {bid_name}")
    md = convert_pdf_to_markdown(pdf_path)
    print(f"Output length: {len(md)} chars")
    print(md[:800])   # preview first 800 chars
```

---

## 📁 Final File Change Summary

| File | Action | What |
|------|--------|------|
| `core/ocr.py` | **CREATE** | Mistral OCR wrapper + provider switch |
| `config/settings.py` | **EDIT** | Add `OCR_PROVIDER`, `MISTRAL_API_KEY` |
| `.env.example` | **EDIT** | Add OCR provider section |
| `pipeline/scraper.py` | **EDIT** | Remove Mineru/vLLM, call `convert_pdf_to_markdown()` |
| `requirements.txt` | **EDIT** | Add `mistralai`, remove `vllm`/`flash-attn`/`Mineru_*` |
| `STANDLONE TEST SCRIPTS/TEST_MISTRAL_OCR.py` | **CREATE** | OCR quality validation |

**Total files touched: 6** (2 new, 4 edits)

---

## ⚡ Mistral OCR API — Key Facts

| Property | Value |
|----------|-------|
| Model | `mistral-ocr-latest` |
| Input | PDF uploaded via Files API |
| Output | Per-page `.markdown` strings |
| Tables | Preserved as Markdown tables |
| Formulas | Rendered as LaTeX |
| Languages | 40+ including Hindi/regional |
| Max file size | 50 MB per file |
| GPU needed | None — pure API call |
| Local server | None — no vLLM startup |
| SDK | `pip install mistralai` |
| API keys | https://console.mistral.ai |

---

## ⚠️ Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Mistral Markdown structure differs from Mineru (parser regex may need tuning) | Run Phase 5 test first; check `core/parser.py` extraction on real output |
| API rate limits hit during bulk scraping | Add `time.sleep(1)` in `_mistral_ocr()`; already have `sleep_between_cards()` in loop |
| Network/API outage | 3-attempt retry with 5s backoff; fallback returns `""` like Mineru did |
| Uploaded files accumulate on Mistral storage | Always call `client.files.delete(file_id)` in `finally` block |
| Missing `MISTRAL_API_KEY` in `.env` | Raise `ValueError("MISTRAL_API_KEY not set in .env")` early in `_mistral_ocr()` |
| Cost per PDF | ~$0.001/page; 10 bids x 5 pages = ~$0.05/run — negligible |

---

## 🔢 Implementation Order

```
Step 1 → core/ocr.py              build & test in isolation
Step 2 → config/settings.py       add new keys
Step 3 → .env.example             document the keys
Step 4 → TEST_MISTRAL_OCR.py      validate OCR quality on existing PDFs
Step 5 → pipeline/scraper.py      wire it all in (biggest change)
Step 6 → requirements.txt         final cleanup
```

---

## ✅ Definition of Done

- [ ] `python main.py --bid "GEM/2026/B/7853146"` runs without vLLM server, produces `.md` via Mistral OCR
- [ ] Markdown output contains correct department name, item name, estimated value
- [ ] `python main.py --once` completes a full scrape run
- [ ] `python main.py --ask "show me pump bids"` still returns correct RAG answers
- [ ] No `vllm` or `Mineru_Document_To_Markdown` imports at startup
- [ ] No GPU memory allocated during scraping phase

---

*Plan authored: September 2026 | Branch: development_v2*
