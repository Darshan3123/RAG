# =========================================================================
# tasks/beat_schedule.py
# Celery Beat Periodic Scheduler Configuration
# =========================================================================
from celery.schedules import crontab
from tasks.celery_app import app
from config.settings import SCRAPE_INTERVAL_MINUTES

app.conf.beat_schedule = {
    "crawl-gem-categories-periodic": {
        "task": "tasks.tier1_scraper.crawl_all_categories",
        "schedule": crontab(minute=f"*/{SCRAPE_INTERVAL_MINUTES}"),
        "args": (2,),  # Target 2 bids per category each cycle
        "options": {"queue": "scraping_queue"},
    },
}
