# =========================================================
# pipeline/__init__.py
# GeM RAG Pipeline package initialization
# =========================================================
"""
GeM RAG Pipeline Package.

Provides high-level scraping and scheduling routines for retrieving, parsing,
and storing GeM bid documents using Playwright and the Mineru VLM engine.
"""

from pipeline.scraper import run_full_scrape, scrape_specific_bid, scrape_bid_type
from pipeline.scheduler import start_scheduler, alert_new_bids

__all__ = [
    "run_full_scrape",
    "scrape_specific_bid",
    "scrape_bid_type",
    "start_scheduler",
    "alert_new_bids",
]
