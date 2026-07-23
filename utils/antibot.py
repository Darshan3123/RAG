# =========================================================
# utils/antibot.py
# Human-like behaviour helpers — random delays, UA rotation
# =========================================================
import random
import time
import os
from config.settings import (
    USER_AGENTS, VIEWPORTS,
    PAGE_LOAD_WAIT, BETWEEN_CARDS_WAIT,
    BETWEEN_PAGES_WAIT, FILTER_CLICK_WAIT,
    PDF_DOWNLOAD_WAIT,
)


# ---------------------------------------------------------
# RANDOM SLEEP
# ---------------------------------------------------------
def sleep_page_load():
    _sleep(*PAGE_LOAD_WAIT)

def sleep_between_cards():
    _sleep(*BETWEEN_CARDS_WAIT)

def sleep_between_pages():
    _sleep(*BETWEEN_PAGES_WAIT)

def sleep_filter_click():
    _sleep(*FILTER_CLICK_WAIT)

def sleep_pdf_download():
    _sleep(*PDF_DOWNLOAD_WAIT)

def _sleep(lo: float, hi: float):
    time.sleep(random.uniform(lo, hi))


# ---------------------------------------------------------
# RANDOM BROWSER PROFILE
# ---------------------------------------------------------
def random_user_agent() -> str:
    return random.choice(USER_AGENTS)

def random_viewport() -> dict:
    return random.choice(VIEWPORTS)


# ---------------------------------------------------------
# STEALTH LAUNCH OPTIONS
# Playwright launch kwargs that reduce bot fingerprint
# ---------------------------------------------------------
def stealth_launch_options() -> dict:
    return {
        "headless": True,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-infobars",
            "--disable-extensions",
            f"--window-size={random_viewport()['width']},"
            f"{random_viewport()['height']}",
        ],
    }

def stealth_context_options() -> dict:
    vp = random_viewport()
    return {
        "user_agent": random_user_agent(),
        "viewport": vp,
        "locale": "en-IN",
        "timezone_id": "Asia/Kolkata",
        "java_script_enabled": True,
        "accept_downloads": True,
        "extra_http_headers": {
            "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,image/webp,*/*;q=0.8"
            ),
            "DNT": "1",
        },
    }


# ---------------------------------------------------------
# HUMAN MOUSE MOVE (optional — call after page load)
# Moves mouse to a random position to simulate real user
# ---------------------------------------------------------
def human_mouse_move(page):
    try:
        vp = page.viewport_size or {"width": 1366, "height": 768}
        x = random.randint(100, vp["width"] - 100)
        y = random.randint(100, vp["height"] - 100)
        page.mouse.move(x, y)
        _sleep(0.2, 0.5)
    except Exception:
        pass
