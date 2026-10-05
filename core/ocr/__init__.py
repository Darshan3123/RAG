# =========================================================
# core/ocr/__init__.py
# Pluggable Multi-Provider Document Intelligence & OCR Engine
# =========================================================
from core.ocr.base import OCRUsage, OCRResult, BaseOCRProvider
from core.ocr.factory import DocumentOCRFactory

__all__ = [
    "OCRUsage",
    "OCRResult",
    "BaseOCRProvider",
    "DocumentOCRFactory",
]
