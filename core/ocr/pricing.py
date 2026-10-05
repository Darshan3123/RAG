# =========================================================
# core/ocr/pricing.py
# Centralized Cost Catalog and Price Calculation for OCR/LLM
# =========================================================
import os
from typing import Dict, Any
from core.ocr.base import OCRUsage

# Global USD to INR currency conversion factor (configurable via .env)
USD_TO_INR_RATE = float(os.getenv("USD_TO_INR_RATE", "86.50"))

# Provider Price Catalog
# Units:
# - per_page: USD cost per page
# - input_per_million: USD cost per 1M input tokens
# - output_per_million: USD cost per 1M output tokens
PRICING_CATALOG: Dict[str, Dict[str, Dict[str, float]]] = {
    "mistral": {
        "mistral-ocr-3-0": {
            "per_page": 0.001,  # $1 per 1,000 pages
            "input_per_million": 0.0,
            "output_per_million": 0.0,
        },
        "mistral-ocr-latest": {
            "per_page": 0.001,
            "input_per_million": 0.0,
            "output_per_million": 0.0,
        },
        "mistral-ocr-4-0": {
            "per_page": 0.002,
            "input_per_million": 0.0,
            "output_per_million": 0.0,
        },
    },
    "gemini": {
        "gemini-3.1-flash-lite": {
            "per_page": 0.0,
            "input_per_million": 0.0375,
            "output_per_million": 0.15,
        },
        "gemini-2.5-flash": {
            "per_page": 0.0,
            "input_per_million": 0.075,
            "output_per_million": 0.30,
        },
        "gemini-1.5-flash": {
            "per_page": 0.0,
            "input_per_million": 0.075,
            "output_per_million": 0.30,
        },
        "gemini-1.5-pro": {
            "per_page": 0.0,
            "input_per_million": 1.25,
            "output_per_million": 5.00,
        },
    },
    "openai": {
        "gpt-4o-mini": {
            "per_page": 0.0,
            "input_per_million": 0.15,
            "output_per_million": 0.60,
        },
        "gpt-4o": {
            "per_page": 0.0,
            "input_per_million": 2.50,
            "output_per_million": 10.00,
        },
    },
    "mineru": {
        "local-vlm": {
            "per_page": 0.0,
            "input_per_million": 0.0,
            "output_per_million": 0.0,
        }
    }
}


def calculate_provider_cost(
    provider: str,
    model: str,
    usage: OCRUsage,
    usd_to_inr_rate: float = USD_TO_INR_RATE
) -> OCRUsage:
    """
    Calculate USD and INR cost for a given OCR/LLM provider and model.
    
    Args:
        provider: Provider name (e.g. 'mistral', 'gemini', 'openai', 'mineru').
        model: Specific model name.
        usage: OCRUsage dataclass containing pages and tokens.
        usd_to_inr_rate: Exchange rate to INR.
        
    Returns:
        Updated OCRUsage dataclass with estimated_cost_usd and estimated_cost_inr.
    """
    provider_rates = PRICING_CATALOG.get(provider.lower(), {})
    # Fallback to first available model rate if exact model not found
    model_rates = provider_rates.get(model.lower())
    if not model_rates and provider_rates:
        model_rates = next(iter(provider_rates.values()))
    elif not model_rates:
        model_rates = {"per_page": 0.0, "input_per_million": 0.0, "output_per_million": 0.0}

    page_cost = usage.pages_processed * model_rates.get("per_page", 0.0)
    input_cost = (usage.input_tokens / 1_000_000.0) * model_rates.get("input_per_million", 0.0)
    output_cost = (usage.output_tokens / 1_000_000.0) * model_rates.get("output_per_million", 0.0)

    total_usd = page_cost + input_cost + output_cost
    total_inr = total_usd * usd_to_inr_rate

    usage.estimated_cost_usd = total_usd
    usage.estimated_cost_inr = total_inr
    usage.details["price_model_used"] = model
    usage.details["usd_to_inr_rate"] = usd_to_inr_rate

    return usage
