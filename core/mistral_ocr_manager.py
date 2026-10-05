"""
Mistral OCR Manager
Handles OCR processing using Mistral AI's OCR API and converts results to Markdown.
"""
from mistralai.client import Mistral
from typing import Any, Dict, Optional, Sequence
import base64
import hashlib
import json
import logging
import os
import pymupdf
import re
import tempfile
import time

try:
    from django.core.cache import cache
except (ImportError, Exception):
    class _InMemoryCache:
        """Lightweight in-memory cache fallback when Django is not installed."""
        def __init__(self):
            self._store = {}
            self._expiry = {}

        def get(self, key, default=None):
            if key in self._store:
                exp = self._expiry.get(key)
                if exp and time.time() > exp:
                    self._store.pop(key, None)
                    self._expiry.pop(key, None)
                    return default
                return self._store[key]
            return default

        def set(self, key, value, timeout=600):
            self._store[key] = value
            if timeout:
                self._expiry[key] = time.time() + timeout
            elif key in self._expiry:
                del self._expiry[key]

        def add(self, key, value, timeout=600):
            if self.get(key) is not None:
                return False
            self.set(key, value, timeout)
            return True

        def delete(self, key):
            self._store.pop(key, None)
            self._expiry.pop(key, None)

    cache = _InMemoryCache()

logger = logging.getLogger(__name__)

# Configuration
MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY', '')
MISTRAL_OCR_MODEL = 'mistral-ocr-3-0'

# All available Mistral OCR models
MISTRAL_OCR_MODELS = [
    'mistral-ocr-latest',
    'mistral-ocr-3-0',
    'mistral-ocr-4-0',
]
OCR_CACHE_TTL_SECONDS = 600
OCR_CACHE_VERSION = "v1"
OCR_CROP_RENDER_DPI = 72
OCR_CROP_WHITE_THRESHOLD = 245
OCR_CROP_PADDING_POINTS = 12




class MistralOCRError(Exception):
    """Custom exception for Mistral OCR errors"""
    pass


class MistralOCRConfigError(MistralOCRError):
    """Raised when Mistral OCR configuration is invalid"""
    pass


class MistralOCRAPIError(MistralOCRError):
    """Raised when Mistral API returns an error"""
    pass


def get_mistral_client() -> Mistral:
    """
    Get initialized Mistral client with API key from environment.
    
    Raises:
        MistralOCRConfigError: If API key is not configured
    """
    if not MISTRAL_API_KEY:
        logger.error("MISTRAL_API_KEY not found in environment variables")
        raise MistralOCRConfigError(
            "Mistral API key is not configured. Please set MISTRAL_API_KEY in your environment variables."
        )
    
    if len(MISTRAL_API_KEY) < 10:
        logger.error("MISTRAL_API_KEY appears to be invalid (too short)")
        raise MistralOCRConfigError(
            "Mistral API key appears to be invalid. Please check your MISTRAL_API_KEY configuration."
        )
    
    try:
        return Mistral(api_key=MISTRAL_API_KEY)
    except Exception as e:
        logger.error(f"Failed to initialize Mistral client: {str(e)}")
        raise MistralOCRConfigError(f"Failed to initialize Mistral client: {str(e)}")


def encode_file(file_path: str) -> str:
    """Encode a file to base64 string."""
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _detect_visible_content_rect(
    page: pymupdf.Page,
    render_dpi: int = OCR_CROP_RENDER_DPI,
    white_threshold: int = OCR_CROP_WHITE_THRESHOLD,
    padding_points: float = OCR_CROP_PADDING_POINTS,
) -> pymupdf.Rect:
    """Return the page area containing non-white pixels, plus a safety margin."""
    scale = render_dpi / 72
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale),
        colorspace=pymupdf.csGRAY,
        alpha=False,
    )
    samples = memoryview(pixmap.samples)
    width, height, stride = pixmap.width, pixmap.height, pixmap.stride

    top = next(
        (
            y
            for y in range(height)
            if any(value < white_threshold for value in samples[y * stride:y * stride + width])
        ),
        None,
    )
    if top is None:
        return page.rect

    bottom = next(
        y
        for y in range(height - 1, top - 1, -1)
        if any(value < white_threshold for value in samples[y * stride:y * stride + width])
    )
    left, right = width, -1
    for y in range(top, bottom + 1):
        row = samples[y * stride:y * stride + width]
        for x, value in enumerate(row):
            if value < white_threshold:
                left = min(left, x)
                right = max(right, x)

    page_rect = page.rect
    x_scale = page_rect.width / width
    y_scale = page_rect.height / height
    content_rect = pymupdf.Rect(
        page_rect.x0 + left * x_scale - padding_points,
        page_rect.y0 + top * y_scale - padding_points,
        page_rect.x0 + (right + 1) * x_scale + padding_points,
        page_rect.y0 + (bottom + 1) * y_scale + padding_points,
    )
    return content_rect & page_rect


def create_whitespace_cropped_pdf(
    file_path: str,
    output_path: Optional[str] = None,
    pages: Optional[Sequence[int]] = None,
) -> str:
    """
    Create an OCR-ready PDF whose selected digital pages are cropped to content.

    Page count and ordering are preserved so the caller can continue to pass the
    original zero-based page numbers to Mistral. A page is considered digital
    only when it has a native searchable text layer. Scanned/image-only and blank
    pages remain unchanged. The caller owns and must delete the returned file
    when ``output_path`` is omitted.
    """
    if not os.path.exists(file_path):
        raise MistralOCRError(f"File not found: {file_path}")

    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix="_ocr_cropped.pdf")
        os.close(fd)

    source = pymupdf.open(file_path)
    cropped = pymupdf.open()
    selected_pages = set(pages) if pages is not None else set(range(len(source)))
    try:
        for page_number, page in enumerate(source):
            is_digital_page = bool(page.get_text("text").strip())
            should_crop = page_number in selected_pages and is_digital_page
            clip = _detect_visible_content_rect(page) if should_crop else page.rect
            output_page = cropped.new_page(width=clip.width, height=clip.height)
            output_page.show_pdf_page(output_page.rect, source, page_number, clip=clip)
            logger.debug(
                "OCR crop page %d: %s -> %s",
                page_number,
                page.rect,
                clip,
            )
        cropped.save(output_path, garbage=4, deflate=True)
    except Exception:
        try:
            os.unlink(output_path)
        except OSError:
            pass
        raise
    finally:
        cropped.close()
        source.close()

    return output_path


def run_ocr(client: Mistral, file_path: str, pages: Optional[Sequence[int]] = None,
            model: Optional[str] = None) -> Any:
    """
    Run OCR on a PDF or image file using Mistral AI.
    
    Supports:
    - PDFs via document_url
    - Images via image_url
    
    Args:
        client: Initialized Mistral client
        file_path: Path to the PDF or image file
        pages: Optional list of 0-indexed page numbers to process (e.g. [0] for page 1)
        model: OCR model to use (default: MISTRAL_OCR_MODEL). Options: mistral-ocr-latest,
               mistral-ocr-3-0, mistral-ocr-4-0.
        
    Returns:
        OCR response object from Mistral
        
    Raises:
        MistralOCRError: If file not found or OCR processing fails
        MistralOCRAPIError: If Mistral API returns an error
    """
    if not os.path.exists(file_path):
        raise MistralOCRError(f"File not found: {file_path}")
    
    ext = os.path.splitext(file_path)[1].lower()
    image_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif'}
    cropped_path = None
    selected_model = model if model else MISTRAL_OCR_MODEL

    try:
        if ext in image_extensions:
            base64_file = encode_file(file_path)
            img_format = 'jpeg' if ext in ['.jpg', '.jpeg'] else ext.lstrip('.')
            process_kwargs = {
                "document": {
                    "type": "image_url",
                    "image_url": f"data:image/{img_format};base64,{base64_file}",
                },
                "model": selected_model,
                "include_image_base64": False,
            }
        else:
            try:
                cropped_path = create_whitespace_cropped_pdf(file_path, pages=pages)
                base64_file = encode_file(cropped_path)
            except Exception as e:
                logger.error(f"Failed to prepare file {file_path} for OCR: {str(e)}")
                raise MistralOCRError(f"Failed to prepare file for OCR: {str(e)}")

            process_kwargs = {
                "document": {
                    "type": "document_url",
                    "document_url": f"data:application/pdf;base64,{base64_file}",
                },
                "model": selected_model,
                "include_image_base64": False,
                "table_format": "html",
                "extract_header": True,
                "extract_footer": True,
            }
            if pages is not None:
                # Validate page numbers against actual PDF page count
                try:
                    doc = pymupdf.open(file_path)
                    total_pages = len(doc)
                    doc.close()
                    valid_pages = [p for p in pages if 0 <= p < total_pages]
                    process_kwargs["pages"] = valid_pages if valid_pages else [0]
                except Exception as e:
                    logger.warning(f"Could not verify page count with pymupdf: {e}")
                    process_kwargs["pages"] = list(pages)

        ocr_response = client.ocr.process(**process_kwargs)
        return ocr_response
    except Exception as e:
        logger.error(f"Mistral API error: {str(e)}")
        error_msg = str(e).lower()
        
        # Check for common API errors
        if "authentication" in error_msg or "api key" in error_msg or "unauthorized" in error_msg or "401" in error_msg:
            raise MistralOCRAPIError(
                "Invalid Mistral API key. Please check your MISTRAL_API_KEY configuration."
            )
        elif "rate limit" in error_msg or "quota" in error_msg or "429" in error_msg:
            raise MistralOCRAPIError(
                "OCR service rate limit exceeded. Please wait a moment and try again."
            )
        elif "timeout" in error_msg:
            raise MistralOCRAPIError(
                "OCR service request timed out. Please try uploading the document again."
            )
        elif "service unavailable" in error_msg or "500" in error_msg or "502" in error_msg or "503" in error_msg or "504" in error_msg or "internal_server_error" in error_msg:
            raise MistralOCRAPIError(
                "OCR service is temporarily unavailable from the provider. Please try again in a few moments."
            )
        else:
            # Try extracting user-friendly message from JSON body if present
            clean_msg = None
            json_match = re.search(r'Body:\s*(\{.*\})', str(e))
            if json_match:
                try:
                    err_json = json.loads(json_match.group(1))
                    if isinstance(err_json, dict) and err_json.get("message"):
                        clean_msg = err_json["message"]
                except Exception:
                    pass
            if clean_msg:
                raise MistralOCRAPIError(f"OCR service error: {clean_msg}")
            raise MistralOCRAPIError("OCR service encountered an error while processing the document. Please try again.")
    finally:
        if cropped_path:
            try:
                os.unlink(cropped_path)
            except OSError as cleanup_error:
                logger.warning("Could not delete cropped OCR file %s: %s", cropped_path, cleanup_error)


def ocr_response_to_dict(ocr_response: Any) -> Dict[str, Any]:
    """
    Convert OCR response object to dictionary.
    
    Args:
        ocr_response: OCR response from Mistral
        
    Returns:
        Dictionary representation of the response
    """
    if hasattr(ocr_response, "model_dump"):
        return ocr_response.model_dump()
    elif hasattr(ocr_response, "dict"):
        return ocr_response.dict()
    return ocr_response


def blocks_to_markdown(page: Dict[str, Any]) -> str:
    """
    Convert a single page's content into markdown.
    
    Handles both:
    - Old format: blocks-based (with include_blocks=True)
    - New format: markdown + tables (mistral-ocr-3-0)
    
    Args:
        page: Page dictionary containing either blocks or markdown/tables
        
    Returns:
        Markdown string for the page
    """
    # New format (mistral-ocr-3-0): has markdown field directly
    if "markdown" in page:
        markdown = page.get("markdown", "").strip()
        
        # If there are tables, embed them
        tables = page.get("tables", [])
        for table in tables:
            table_id = table.get("id", "")
            table_content = table.get("content", "")
            # Replace markdown references like [tbl-0.html](tbl-0.html) with actual content
            if table_id:
                markdown = markdown.replace(f"[{table_id}]({table_id})", table_content)
        
        return markdown
    
    # Old format (include_blocks=True): process blocks
    blocks = page.get("blocks") or []
    tables = page.get("tables") or []
    tables_by_id = {table.get("id"): table for table in tables}

    # Reading order: sort by vertical position first, then horizontal
    ordered_blocks = sorted(
        blocks,
        key=lambda b: (b.get("top_left_y", 0), b.get("top_left_x", 0)),
    )

    md_parts = []

    for block in ordered_blocks:
        btype = block.get("type")
        content = block.get("content", "")

        if btype == "table":
            table_id = block.get("table_id")
            table = tables_by_id.get(table_id)
            if table:
                # Embed the table's HTML directly (raw HTML is valid in markdown)
                md_parts.append(table["content"])
            else:
                md_parts.append(content)
        else:
            # title, text, signature, footer, header, etc. -> content as-is
            md_parts.append(content)

    return "\n\n".join(part for part in md_parts if part)


def ocr_json_to_markdown(data: Dict[str, Any]) -> str:
    """
    Convert full OCR response dict into one markdown string, page by page.
    
    Args:
        data: OCR response dictionary
        
    Returns:
        Complete markdown string with all pages separated by horizontal rules
    """
    pages = data.get("pages") or []
    page_markdowns = [blocks_to_markdown(page) for page in pages]

    # Separate pages with a horizontal rule
    return "\n\n---\n\n".join(page_markdowns)


def process_pdf_to_markdown(file_path: str, save_json: bool = False, 
                           output_dir: Optional[str] = None,
                           pages: Optional[Sequence[int]] = None,
                           model: Optional[str] = None) -> str:
    """
    Process a PDF file through Mistral OCR and convert to markdown.
    
    Args:
        file_path: Path to the PDF file
        save_json: Whether to save intermediate JSON output
        output_dir: Directory to save outputs (defaults to same as input file)
        pages: Optional list of 0-indexed page numbers to process (e.g. [0] for page 1)
        model: OCR model to use (default: MISTRAL_OCR_MODEL). Options: mistral-ocr-latest,
               mistral-ocr-3-0, mistral-ocr-4-0.
        
    Returns:
        Markdown string content
        
    Raises:
        MistralOCRConfigError: If API key is not configured
        MistralOCRError: If file not found or processing fails
        MistralOCRAPIError: If Mistral API returns an error
    """
    if not os.path.exists(file_path):
        raise MistralOCRError(f"File not found: {file_path}")
    
    try:
        # Initialize client (validates API key)
        client = get_mistral_client()
        
        # Run OCR
        ocr_response = run_ocr(client, file_path, pages=pages, model=model)
        data = ocr_response_to_dict(ocr_response)
        
        # Save JSON if requested
        if save_json:
            pdf_name = os.path.splitext(os.path.basename(file_path))[0]
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                json_path = os.path.join(output_dir, f"{pdf_name}_mistral_ocr.json")
            else:
                json_path = os.path.join(
                    os.path.dirname(file_path), 
                    f"{pdf_name}_mistral_ocr.json"
                )
            
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved OCR JSON -> {json_path}")
        
        # Convert to markdown
        markdown_text = ocr_json_to_markdown(data)
        
        # If Mistral document OCR returned sparse text on a PDF (e.g. scanned ID card or cropped image inside PDF),
        # retry with Mistral's image OCR endpoint by rendering pages to images
        if not markdown_text or len(markdown_text.strip()) < 10:
            logger.info(f"Mistral document_url produced sparse text for {file_path}, retrying with Mistral image_url")
            try:
                doc = pymupdf.open(file_path)
                total_pages = len(doc)
                target_pages = [p for p in pages if 0 <= p < total_pages] if pages else list(range(total_pages))
                image_parts = []
                for p_idx in target_pages:
                    pix = doc[p_idx].get_pixmap(dpi=200)
                    b64_img = base64.b64encode(pix.tobytes("jpeg")).decode("utf-8")
                    img_resp = client.ocr.process(
                        model=model if model else MISTRAL_OCR_MODEL,
                        document={
                            "type": "image_url",
                            "image_url": f"data:image/jpeg;base64,{b64_img}",
                        }
                    )
                    img_dict = ocr_response_to_dict(img_resp)
                    img_md = ocr_json_to_markdown(img_dict)
                    if img_md.strip():
                        image_parts.append(img_md.strip())
                doc.close()
                if image_parts:
                    markdown_text = "\n\n---\n\n".join(image_parts)
                    logger.info(f"Mistral image_url successfully extracted {len(markdown_text)} chars from {file_path}")
            except Exception as retry_err:
                logger.warning(f"Mistral image_url retry encountered error: {retry_err}")
                
        if not markdown_text or len(markdown_text.strip()) < 10:
            logger.warning(f"Mistral OCR produced very little text for file: {file_path}")
            raise MistralOCRError("OCR produced no meaningful content from the document")
        
        return markdown_text
        
    except (MistralOCRConfigError, MistralOCRAPIError, MistralOCRError):
        # Re-raise our custom exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Unexpected error processing {file_path}: {str(e)}")
        raise MistralOCRError(f"Failed to process PDF: {str(e)}")


def process_pdf_to_markdown_file(file_path: str, output_path: Optional[str] = None,
                                 save_json: bool = False) -> str:
    """
    Process a PDF file through Mistral OCR and save as markdown file.
    
    Args:
        file_path: Path to the PDF file
        output_path: Path for output markdown file (defaults to same location as input)
        save_json: Whether to save intermediate JSON output
        
    Returns:
        Path to the generated markdown file
    """
    # Generate markdown
    markdown_text = process_pdf_to_markdown(file_path, save_json=save_json)
    
    # Determine output path
    if output_path is None:
        pdf_name = os.path.splitext(os.path.basename(file_path))[0]
        output_path = os.path.join(
            os.path.dirname(file_path),
            f"{pdf_name}_mistral_ocr.md"
        )
    
    # Save markdown
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(markdown_text)
    
    print(f"Saved Markdown -> {output_path}")
    return output_path


def process_uploaded_file_to_markdown(
    file_obj,
    filename: str,
    pages: Optional[Sequence[int]] = None,
    return_hash: bool = False,
    model: Optional[str] = None,
) -> str | tuple[str, str]:
    """
    Process an uploaded file object (Django UploadedFile) through Mistral OCR.

    Deduplication uses a Redis distributed lock (cache.add = SETNX) so that
    regardless of how many users upload the same file simultaneously, only one
    Gunicorn worker calls the Mistral API. All others poll Redis until the
    result is stored, then return it directly.

    Works correctly with sync Gunicorn workers — each worker handles one
    request at a time, so no in-process concurrency handling is needed.

    Args:
        file_obj: Django UploadedFile or file-like object with .read() method
        filename: Original filename (used for logging/debugging)
        pages: Optional list of 0-indexed page numbers to process (e.g. [0] for page 1)
        return_hash: If True, returns a tuple of (markdown_text, sha256_hash)
        model: Optional OCR model to use (e.g. 'mistral-ocr-latest')

    Returns:
        Markdown string content, or (Markdown string content, sha256_hash) if return_hash=True

    Raises:
        MistralOCRConfigError: If API key is not configured
        MistralOCRError: If processing fails
        MistralOCRAPIError: If Mistral API returns an error
    """
    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)

    file_content = file_obj.read()
    if not file_content:
        raise MistralOCRError("Uploaded file is empty")

    sha256_hash = hashlib.sha256(file_content).hexdigest()
    pages_key = ",".join(str(p) for p in pages) if pages is not None else "all"
    model_key = model if model else MISTRAL_OCR_MODEL
    cache_key = f"ocr_cache:{OCR_CACHE_VERSION}:{sha256_hash}:{pages_key}:{model_key}"
    lock_key  = f"ocr_lock:{OCR_CACHE_VERSION}:{sha256_hash}:{pages_key}:{model_key}"
    h = sha256_hash[:8]

    # ── 1. Already cached in Redis? ───────────────────────────────────────────
    cached_md = cache.get(cache_key)
    if cached_md:
        logger.info("[OCR CACHE] HIT '%s' (%s) — skipping Mistral API call", filename, h)
        return (cached_md, sha256_hash) if return_hash else cached_md

    # ── 2. Try to acquire distributed lock (Redis SETNX) ─────────────────────
    # cache.add() is atomic — only succeeds if key doesn't exist yet.
    acquired_lock = cache.add(lock_key, "1", timeout=300)

    if not acquired_lock:
        # Another worker holds the lock → poll Redis until result appears.
        logger.info("[OCR CACHE] WAIT '%s' (%s) — another worker is calling Mistral, polling…", filename, h)
        poll_interval = 2   # seconds between checks
        max_wait = 240      # seconds total
        waited = 0
        cached_md = None
        while waited < max_wait:
            time.sleep(poll_interval)
            waited += poll_interval
            cached_md = cache.get(cache_key)
            if cached_md:
                break
            # Lock gone but no result → that worker crashed, take over.
            if not cache.get(lock_key):
                logger.warning("[OCR CACHE] LOCK EXPIRED '%s' (%s) — previous worker may have crashed, retrying OCR", filename, h)
                cache.add(lock_key, "1", timeout=300)   # re-acquire
                break

        if cached_md:
            logger.info("[OCR CACHE] RESOLVED '%s' (%s) — reusing result from other worker", filename, h)
            return (cached_md, sha256_hash) if return_hash else cached_md
        # Fall through — we re-acquired the lock above, run OCR ourselves.

    # ── 3. We own the lock — call Mistral ────────────────────────────────────
    tmp_path = None
    try:
        ext = os.path.splitext(filename)[1].lower() if filename else ''
        image_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif'}
        is_image = ext in image_extensions
        tmp_suffix = ext if is_image else '.pdf'
        with tempfile.NamedTemporaryFile(suffix=tmp_suffix, delete=False) as tmp_file:
            tmp_file.write(file_content)
            tmp_path = tmp_file.name

        logger.info("[OCR CACHE] MISS '%s' (%s) — calling Mistral API now (model=%s)", filename, h, model_key)

        if is_image:
            client = get_mistral_client()
            ocr_response = run_ocr(client, tmp_path, model=model)
            data = ocr_response_to_dict(ocr_response)
            markdown_text = ocr_json_to_markdown(data)
            if not markdown_text or len(markdown_text.strip()) < 10:
                raise MistralOCRError("OCR produced no meaningful content from the document")
        else:
            markdown_text = process_pdf_to_markdown(tmp_path, save_json=False, pages=pages, model=model)

        cache.set(cache_key, markdown_text, timeout=OCR_CACHE_TTL_SECONDS)
        cache.delete(lock_key)
        logger.info("[OCR CACHE] STORED '%s' (%s) — %d chars cached, lock released", filename, h, len(markdown_text))

        return (markdown_text, sha256_hash) if return_hash else markdown_text

    except (MistralOCRConfigError, MistralOCRAPIError, MistralOCRError):
        cache.delete(lock_key)
        raise
    except Exception as e:
        cache.delete(lock_key)
        logger.error(f"Unexpected error processing uploaded file {filename}: {str(e)}")
        raise MistralOCRError(f"Failed to process uploaded file: {str(e)}") from e
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception as ex:
                logger.warning(f"Could not delete temporary file {tmp_path}: {ex}")
