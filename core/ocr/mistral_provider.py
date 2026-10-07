# =========================================================
# core/ocr/mistral_provider.py
# Mistral OCR Document Intelligence Provider
# =========================================================
import os
import time
import json
import logging
from typing import Optional, Sequence, Dict, Any

import pymupdf

from core.ocr.base import BaseOCRProvider, OCRResult, OCRUsage
from core.ocr.pricing import calculate_provider_cost
from core.mistral_ocr_manager import (
    get_mistral_client,
    run_ocr,
    ocr_response_to_dict,
    ocr_json_to_markdown,
    process_pdf_to_markdown,
    MistralOCRError,
    MISTRAL_OCR_MODEL,
)

logger = logging.getLogger(__name__)


class MistralOCRProvider(BaseOCRProvider):
    """
    Mistral OCR Provider implementation using Mistral AI's OCR API.
    Supports whitespace margin pre-cropping, HTML table extraction, and image fallback.
    """

    def __init__(self, model: Optional[str] = None):
        selected_model = model or os.getenv("MISTRAL_OCR_MODEL", MISTRAL_OCR_MODEL)
        super().__init__(model=selected_model)

    @property
    def name(self) -> str:
        return "mistral"

    def convert_pdf_to_markdown(
        self,
        pdf_path: str,
        save_json: bool = False,
        output_dir: Optional[str] = None,
        pages: Optional[Sequence[int]] = None,
        **kwargs
    ) -> OCRResult:
        """
        Process a PDF file via Mistral OCR and return structured OCRResult.
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF document not found: {pdf_path}")

        start_time = time.time()
        effective_model = self.model or MISTRAL_OCR_MODEL

        # Count total pages via PyMuPDF if available
        total_pages = 1
        try:
            doc = pymupdf.open(pdf_path)
            total_pages = len(doc)
            doc.close()
        except Exception:
            pass

        if pages is not None:
            pages_processed = len(pages)
        else:
            pages_processed = total_pages

        # Run Mistral OCR
        client = get_mistral_client()
        ocr_response = run_ocr(client, pdf_path, pages=pages, model=effective_model)
        raw_dict = ocr_response_to_dict(ocr_response)

        # Update actual pages count from OCR response if available
        resp_pages = raw_dict.get("pages")
        if isinstance(resp_pages, list) and len(resp_pages) > 0:
            pages_processed = len(resp_pages)

        # Convert to markdown with embedded HTML tables
        markdown_text = ocr_json_to_markdown(raw_dict)

        # Save raw JSON if requested
        if save_json:
            pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
            target_dir = output_dir or os.path.dirname(pdf_path)
            os.makedirs(target_dir, exist_ok=True)
            json_path = os.path.join(target_dir, f"{pdf_name}_mistral_ocr.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(raw_dict, f, ensure_ascii=False, indent=2)
            logger.info("Saved Mistral OCR JSON artifact -> %s", json_path)

        latency = time.time() - start_time

        # Build usage telemetry
        usage = OCRUsage(
            pages_processed=pages_processed,
            input_tokens=0,
            output_tokens=len(markdown_text) // 4,  # Approx output tokens
            latency_seconds=latency,
            details={
                "pdf_path": pdf_path,
                "total_doc_pages": total_pages,
            }
        )

        # Compute cost
        usage = self.calculate_cost(usage, effective_model)

        return OCRResult(
            markdown=markdown_text,
            provider=self.name,
            model=effective_model,
            usage=usage,
            raw_response=raw_dict,
        )

    def calculate_cost(self, usage: OCRUsage, model: str) -> OCRUsage:
        return calculate_provider_cost(self.name, model, usage)
