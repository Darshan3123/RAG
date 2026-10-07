# =========================================================
# core/ocr/gemini_provider.py
# Google Gemini Document Intelligence OCR Provider
# =========================================================
import os
import time
import json
import base64
import logging
from typing import Optional, Dict, Any
import requests

import pymupdf

from core.ocr.base import BaseOCRProvider, OCRResult, OCRUsage
from core.ocr.pricing import calculate_provider_cost

logger = logging.getLogger(__name__)

GEMINI_OCR_SYSTEM_PROMPT = """You are an expert document OCR and layout analysis engine.
Transcribe this government procurement / bid document into clean, comprehensive Markdown.

STRICT FORMATTING REQUIREMENTS:
1. TABLES AS HTML: Format ALL tables (schedules, consignees, specifications, financials) as standard HTML <table> tags with <thead>, <tbody>, <tr>, <th>, and <td>. Do NOT use markdown pipe tables.
2. PRESERVE STRUCTURE: Maintain complete section hierarchies, headers, footers, item lists, and buyer-added ATC clauses.
3. RAW OUTPUT ONLY: Return ONLY the transcribed document content. Do not include introductory notes, explanations, or code fencing (no ```markdown).
"""


class GeminiOCRProvider(BaseOCRProvider):
    """
    Google Gemini Document Intelligence OCR Provider.
    Sends PDF document bytes to Gemini Multimodal API and extracts Markdown with HTML tables.
    """

    def __init__(self, model: Optional[str] = None):
        selected_model = model or os.getenv("GEMINI_OCR_MODEL", "gemini-2.5-flash")
        super().__init__(model=selected_model)
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()

    @property
    def name(self) -> str:
        return "gemini"

    def convert_pdf_to_markdown(
        self,
        pdf_path: str,
        save_json: bool = False,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> OCRResult:
        """
        Process a PDF document via Gemini multimodal API.
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF document not found: {pdf_path}")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not configured in environment")

        start_time = time.time()
        effective_model = self.model or "gemini-2.5-flash"

        # Count total pages via PyMuPDF
        total_pages = 1
        try:
            doc = pymupdf.open(pdf_path)
            total_pages = len(doc)
            doc.close()
        except Exception:
            pass

        # Encode PDF to base64
        with open(pdf_path, "rb") as f:
            pdf_b64 = base64.b64encode(f.read()).decode("utf-8")

        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{effective_model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "application/pdf",
                                "data": pdf_b64
                            }
                        },
                        {
                            "text": GEMINI_OCR_SYSTEM_PROMPT
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
            }
        }

        resp = requests.post(endpoint, json=payload, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini OCR API error ({resp.status_code}): {resp.text}")

        resp_json = resp.json()
        raw_markdown = ""
        candidates = resp_json.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            raw_markdown = "".join(p.get("text", "") for p in parts).strip()

        # Clean any accidental markdown code fences
        if raw_markdown.startswith("```markdown"):
            raw_markdown = raw_markdown[len("```markdown"):].strip()
        elif raw_markdown.startswith("```"):
            raw_markdown = raw_markdown[3:].strip()
        if raw_markdown.endswith("```"):
            raw_markdown = raw_markdown[:-3].strip()

        # Extract actual token counts
        usage_meta = resp_json.get("usageMetadata", {})
        input_tokens = usage_meta.get("promptTokenCount", 0)
        output_tokens = usage_meta.get("candidatesTokenCount", 0)

        latency = time.time() - start_time

        # Save raw JSON if requested
        if save_json:
            pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
            target_dir = output_dir or os.path.dirname(pdf_path)
            os.makedirs(target_dir, exist_ok=True)
            json_path = os.path.join(target_dir, f"{pdf_name}_gemini_ocr.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(resp_json, f, ensure_ascii=False, indent=2)
            logger.info("Saved Gemini OCR JSON artifact -> %s", json_path)

        usage = OCRUsage(
            pages_processed=total_pages,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_seconds=latency,
            details={
                "pdf_path": pdf_path,
                "total_doc_pages": total_pages,
                "gemini_usage_metadata": usage_meta,
            }
        )

        usage = self.calculate_cost(usage, effective_model)

        return OCRResult(
            markdown=raw_markdown,
            provider=self.name,
            model=effective_model,
            usage=usage,
            raw_response=resp_json,
        )

    def calculate_cost(self, usage: OCRUsage, model: str) -> OCRUsage:
        return calculate_provider_cost(self.name, model, usage)
