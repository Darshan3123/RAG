# =========================================================
# core/ocr/factory.py
# Factory for Instantiating Document Intelligence OCR Providers
# =========================================================
import os
import logging
from typing import Optional, Dict, Type

from core.ocr.base import BaseOCRProvider
from core.ocr.mistral_provider import MistralOCRProvider
from core.ocr.gemini_provider import GeminiOCRProvider
from core.ocr.openai_provider import OpenAIOCRProvider

logger = logging.getLogger(__name__)


class DocumentOCRFactory:
    """
    Factory class that returns the active OCR provider based on configuration.
    Allows effortless switching between Mistral, Gemini, and OpenAI.
    """

    _REGISTRY: Dict[str, Type[BaseOCRProvider]] = {
        "mistral": MistralOCRProvider,
        "gemini": GeminiOCRProvider,
        "openai": OpenAIOCRProvider,
    }

    @classmethod
    def register_provider(cls, name: str, provider_cls: Type[BaseOCRProvider]) -> None:
        """Register a custom OCR provider class."""
        cls._REGISTRY[name.lower()] = provider_cls

    @classmethod
    def list_available_providers(cls) -> list[str]:
        """List all supported OCR provider names."""
        return list(cls._REGISTRY.keys())

    @classmethod
    def get_provider(
        cls,
        provider_name: Optional[str] = None,
        model: Optional[str] = None
    ) -> BaseOCRProvider:
        """
        Instantiate the requested or configured OCR provider.
        
        Args:
            provider_name: 'mistral' | 'gemini' | 'openai' | 'mineru' (defaults to OCR_PROVIDER env var).
            model: Optional model override for the provider.
            
        Returns:
            An instance of BaseOCRProvider.
            
        Raises:
            ValueError: If the provider is unsupported or invalid.
        """
        effective_name = (provider_name or os.getenv("OCR_PROVIDER", "mistral")).strip().lower()

        provider_cls = cls._REGISTRY.get(effective_name)
        if not provider_cls:
            available = ", ".join(cls._REGISTRY.keys())
            raise ValueError(
                f"Unsupported OCR provider '{effective_name}'. "
                f"Available providers: {available}"
            )

        logger.info("Initializing OCR provider: %s (model: %s)", effective_name, model or "default")
        return provider_cls(model=model)
