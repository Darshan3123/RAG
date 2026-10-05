# =========================================================
# core/ocr/base.py
# Base Definitions and Abstract Interface for OCR Providers
# =========================================================
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class OCRUsage:
    """Telemetry and cost tracking container for an OCR operation."""
    pages_processed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_seconds: float = 0.0
    estimated_cost_usd: float = 0.0
    estimated_cost_inr: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert telemetry to a JSON-serializable dictionary."""
        return {
            "pages_processed": self.pages_processed,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_seconds": round(self.latency_seconds, 3),
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "estimated_cost_inr": round(self.estimated_cost_inr, 4),
            "details": self.details,
        }


@dataclass
class OCRResult:
    """Standardized output returned by every OCR provider."""
    markdown: str
    provider: str
    model: str
    usage: OCRUsage = field(default_factory=OCRUsage)
    raw_response: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result summary to a dictionary."""
        return {
            "provider": self.provider,
            "model": self.model,
            "markdown_length": len(self.markdown),
            "usage": self.usage.to_dict(),
        }


class BaseOCRProvider(ABC):
    """Abstract Base Class for all Document OCR and Vision Providers."""

    def __init__(self, model: Optional[str] = None):
        self.model = model

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'mistral', 'gemini', 'openai', 'mineru')."""
        pass

    @abstractmethod
    def convert_pdf_to_markdown(
        self,
        pdf_path: str,
        save_json: bool = False,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> OCRResult:
        """
        Convert a PDF file to markdown text with embedded HTML <table> elements.
        
        Args:
            pdf_path: Path to the PDF file.
            save_json: Whether to persist intermediate JSON metadata.
            output_dir: Directory to save artifacts.
            **kwargs: Provider-specific execution options.
            
        Returns:
            OCRResult containing markdown, telemetry, and calculated cost.
        """
        pass

    @abstractmethod
    def calculate_cost(self, usage: OCRUsage, model: str) -> OCRUsage:
        """Compute estimated USD and INR costs based on usage metrics."""
        pass
