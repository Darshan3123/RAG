# =========================================================
# core/ocr/openai_provider.py
# OpenAI / ChatGPT Document Intelligence OCR Provider
# =========================================================
import os
import time
import json
import base64
import logging
from typing import Optional, Dict, Any

import pymupdf

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from core.ocr.base import BaseOCRProvider, OCRResult, OCRUsage
from core.ocr.pricing import calculate_provider_cost

logger = logging.getLogger(__name__)

OPENAI_OCR_PROMPT = """You are an expert document OCR engine.
Transcribe the provided document page images into clean, complete Markdown.

CRITICAL REQUIREMENTS:
1. TABLES AS HTML: Format ALL tables as standard HTML <table> tags with <thead>, <tbody>, <tr>, <th>, and <td>. Do NOT use markdown pipe tables.
2. PRESERVE STRUCTURE: Maintain headers, item lists, buyer ATC clauses, and consignee data.
3. RAW CONTENT ONLY: Return ONLY the markdown transcription without introductory commentary or markdown fences.
"""


class OpenAIOCRProvider(BaseOCRProvider):
    """
    OpenAI / ChatGPT Document Vision Provider.
    Renders PDF pages to images and prompts GPT-4o or GPT-4o-mini for structured Markdown with HTML tables.
    """

    def __init__(self, model: Optional[str] = None):
        selected_model = model or os.getenv("OPENAI_OCR_MODEL", "gpt-4o-mini")
        super().__init__(model=selected_model)
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()

    @property
    def name(self) -> str:
        return "openai"

    def convert_pdf_to_markdown(
        self,
        pdf_path: str,
        save_json: bool = False,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> OCRResult:
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF document not found: {pdf_path}")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not configured in environment")
        if not OpenAI:
            raise ImportError("openai package is required for OpenAIOCRProvider. Run: pip install openai")

        start_time = time.time()
        effective_model = self.model or "gpt-4o-mini"
        client = OpenAI(api_key=self.api_key)

        doc = pymupdf.open(pdf_path)
        total_pages = len(doc)
        content_parts = [{"type": "text", "text": OPENAI_OCR_PROMPT}]

        for page_idx in range(total_pages):
            pix = doc[page_idx].get_pixmap(dpi=150)
            img_b64 = base64.b64encode(pix.tobytes("jpeg")).decode("utf-8")
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{img_b64}",
                    "detail": "high"
                }
            })
        doc.close()

        # Call OpenAI Chat Completions API
        response = client.chat.completions.create(
            model=effective_model,
            messages=[{"role": "user", "content": content_parts}],
            temperature=0.0,
        )

        raw_markdown = response.choices[0].message.content or ""
        # Strip code fences if present
        if raw_markdown.startswith("```markdown"):
            raw_markdown = raw_markdown[len("```markdown"):].strip()
        elif raw_markdown.startswith("```"):
            raw_markdown = raw_markdown[3:].strip()
        if raw_markdown.endswith("```"):
            raw_markdown = raw_markdown[:-3].strip()

        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0

        latency = time.time() - start_time

        raw_dict = response.model_dump() if hasattr(response, "model_dump") else {}

        if save_json:
            pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
            target_dir = output_dir or os.path.dirname(pdf_path)
            os.makedirs(target_dir, exist_ok=True)
            json_path = os.path.join(target_dir, f"{pdf_name}_openai_ocr.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(raw_dict, f, ensure_ascii=False, indent=2)
            logger.info("Saved OpenAI OCR JSON artifact -> %s", json_path)

        usage = OCRUsage(
            pages_processed=total_pages,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_seconds=latency,
            details={
                "pdf_path": pdf_path,
                "total_doc_pages": total_pages,
            }
        )

        usage = self.calculate_cost(usage, effective_model)

        return OCRResult(
            markdown=raw_markdown,
            provider=self.name,
            model=effective_model,
            usage=usage,
            raw_response=raw_dict,
        )

    def calculate_cost(self, usage: OCRUsage, model: str) -> OCRUsage:
        return calculate_provider_cost(self.name, model, usage)
