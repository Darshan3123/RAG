# =========================================================
# core/ocr/mineru_provider.py
# Mineru VLM Local GPU Document Intelligence Provider
# =========================================================
import os
import time
import json
import logging
import asyncio
import threading
from typing import Optional, Dict, Any

import pymupdf

try:
    from Mineru_Document_To_Markdown import async_convert_document
except ImportError:
    async_convert_document = None

from core.ocr.base import BaseOCRProvider, OCRResult, OCRUsage
from core.ocr.pricing import calculate_provider_cost

logger = logging.getLogger(__name__)


class _AsyncWorker:
    """Helper runner for executing async functions synchronously in a dedicated loop."""
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()


class MineruVLMProvider(BaseOCRProvider):
    """
    Mineru VLM Local GPU OCR Provider.
    Executes local vision-language model inference via vLLM server.
    """

    def __init__(self, model: Optional[str] = None):
        selected_model = model or "local-vlm"
        super().__init__(model=selected_model)
        self._worker = None

    @property
    def name(self) -> str:
        return "mineru"

    def _get_worker(self) -> _AsyncWorker:
        if self._worker is None:
            self._worker = _AsyncWorker()
        return self._worker

    def convert_pdf_to_markdown(
        self,
        pdf_path: str,
        save_json: bool = False,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> OCRResult:
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF document not found: {pdf_path}")
        if not async_convert_document:
            raise ImportError(
                "Mineru_Document_To_Markdown is not installed. "
                "Ensure local GPU dependencies are present."
            )

        start_time = time.time()
        effective_model = self.model or "local-vlm"

        total_pages = 1
        try:
            doc = pymupdf.open(pdf_path)
            total_pages = len(doc)
            doc.close()
        except Exception:
            pass

        worker = self._get_worker()
        conv_result = worker.run(
            async_convert_document(
                input_path=pdf_path,
                output_dir=None,
                backend="vlm-engine",
                formula_enable=True,
                table_enable=True,
            )
        )

        raw_markdown = ""
        raw_dict = {}
        if isinstance(conv_result, dict):
            raw_dict = conv_result
            raw_markdown = conv_result.get("markdown", "")
        elif isinstance(conv_result, str):
            raw_markdown = conv_result

        latency = time.time() - start_time

        if save_json and raw_dict:
            pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
            target_dir = output_dir or os.path.dirname(pdf_path)
            os.makedirs(target_dir, exist_ok=True)
            json_path = os.path.join(target_dir, f"{pdf_name}_mineru_ocr.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(raw_dict, f, ensure_ascii=False, indent=2)
            logger.info("Saved Mineru OCR JSON artifact -> %s", json_path)

        usage = OCRUsage(
            pages_processed=total_pages,
            input_tokens=0,
            output_tokens=len(raw_markdown) // 4,
            latency_seconds=latency,
            details={
                "pdf_path": pdf_path,
                "total_doc_pages": total_pages,
                "backend": "local-vlm",
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
