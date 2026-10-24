# =========================================================================
# tasks/celery_app.py
# Celery Application Configuration for GeMBridge Distributed Pipeline
# =========================================================================
import os
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
from celery import Celery
from celery.signals import worker_ready
from kombu import Queue
from utils.logger import get_logger
from config.settings import (
    CELERY_BROKER_URL,
    CELERY_RESULT_BACKEND,
)

# Initialize Celery app
app = Celery("gem_bridge")
log = get_logger("celery_app")

# Queues configuration
app.conf.update(
    broker_url=CELERY_BROKER_URL,
    result_backend=CELERY_RESULT_BACKEND,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    
    # Task reliability settings
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    
    # Explicit task routing to dedicated queues
    task_queues=[
        Queue("scraping_queue", routing_key="scraping.#"),
        Queue("document_queue", routing_key="document.#"),
        Queue("atc_rag_queue", routing_key="atc_rag.#"),
    ],
    task_routes={
        "tasks.tier1_scraper.*": {"queue": "scraping_queue"},
        "tasks.tier2_document.*": {"queue": "document_queue"},
        "tasks.tier3_atc_rag.*": {"queue": "atc_rag_queue"},
    },
    
    # Auto-discover task modules
    include=[
        "tasks.tier1_scraper",
        "tasks.tier2_document",
        "tasks.tier3_atc_rag",
    ],
)

# Explicit module imports to guarantee task registration on boot
import tasks.tier1_scraper  # noqa: F401
import tasks.tier2_document  # noqa: F401
import tasks.tier3_atc_rag  # noqa: F401
import tasks.beat_schedule  # noqa: F401


@worker_ready.connect
def on_worker_ready(sender, **kwargs):
    """
    Auto-dispatches an initial scrape on boot if AUTO_START_SCRAPER_ON_BOOT is enabled.
    Guarded to only fire from the scraper worker.
    """
    hostname = str(getattr(sender, "hostname", ""))
    if "scraper" in hostname:
        auto_start = os.getenv("AUTO_START_SCRAPER_ON_BOOT", "true").lower() in ("1", "true", "yes", "on")
        if auto_start:
            log.info(f"🚀 [{hostname}] Scraper worker ready — AUTO_START_SCRAPER_ON_BOOT is enabled. Auto-dispatching crawl...")
            try:
                from tasks.tier1_scraper import crawl_all_categories
                crawl_all_categories.delay()
            except Exception as e:
                log.error(f"Failed to auto-dispatch crawl on startup: {e}", exc_info=True)

if __name__ == "__main__":
    app.start()

