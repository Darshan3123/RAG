# =========================================================================
# tasks/beat_schedule.py
# Celery Beat Periodic Scheduler Configuration
# =========================================================================
from celery.schedules import crontab
from tasks.celery_app import app
from config.settings import SCRAPE_INTERVAL_MINUTES, TARGET_PER_TYPE

# Target count per category: positive integer caps the crawl, None/0 enables unlimited delta crawl
_periodic_target = TARGET_PER_TYPE if TARGET_PER_TYPE > 0 else None

app.conf.beat_schedule = {
    "crawl-gem-categories-periodic": {
        "task": "tasks.tier1_scraper.crawl_all_categories",
        "schedule": crontab(minute=f"*/{SCRAPE_INTERVAL_MINUTES}"),
        "args": (_periodic_target,),
        "options": {"queue": "scraping_queue"},
    },
}
