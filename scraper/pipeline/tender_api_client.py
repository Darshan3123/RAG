# =========================================================
# pipeline/tender_api_client.py
# HTTP client for the tender API
# Handles pagination, auth, rate limiting
# =========================================================
from __future__ import annotations
import time
import requests
from shared.utils.logger import get_logger

log = get_logger("tender_api")

# ── All values driven by config/settings.py (.env) ───────
from shared.config.settings import (
    TENDER_API_BASE_URL   as API_BASE_URL,
    TENDER_API_KEY        as API_KEY,
    TENDER_API_TIMEOUT    as API_TIMEOUT,
    TENDER_API_PAGE_SIZE  as API_PAGE_SIZE,
    TENDER_API_RATE_DELAY as API_RATE_DELAY,
)


class TenderApiClient:

    def __init__(self):
        self.session = requests.Session()
        if API_KEY:
            self.session.headers.update({
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            })

    # ── Active Tenders ─────────────────────────────────────
    def fetch_active_tenders(
        self,
        category: str = "",
        state: str = "",
        platform: str = "",
        page: int = 1,
        page_size: int = API_PAGE_SIZE,
    ) -> list[dict]:
        """
        Fetch open/active tenders.
        Returns raw list (Format 1 objects).
        """
        params = {
            "page":      page,
            "page_size": page_size,
            "status":    "OPEN",
        }
        if category: params["category"]  = category
        if state:    params["state"]     = state
        if platform: params["platform"]  = platform

        url = f"{API_BASE_URL}/active-tenders"
        return self._get(url, params)

    # ── Tender Results ─────────────────────────────────────
    def fetch_tender_results(
        self,
        category: str = "",
        state: str = "",
        page: int = 1,
        page_size: int = API_PAGE_SIZE,
    ) -> list[dict]:
        """
        Fetch completed/awarded tenders (AOC).
        Returns raw list (Format 2 objects with _source wrapper).
        """
        params = {
            "page":      page,
            "page_size": page_size,
            "status":    "AOC",
        }
        if category: params["category"] = category
        if state:    params["state"]    = state

        url = f"{API_BASE_URL}/tender-results"
        return self._get(url, params)

    # ── Paginated fetch — returns ALL pages ───────────────
    def fetch_all_active(
        self,
        category: str = "",
        state: str = "",
        max_pages: int = 10,
    ) -> list[dict]:
        """Fetch all pages of active tenders."""
        all_items = []
        for page in range(1, max_pages + 1):
            items = self.fetch_active_tenders(
                category=category, state=state, page=page
            )
            if not items:
                log.info(f"  No more active tenders at page {page}")
                break
            all_items.extend(items)
            log.info(f"  Fetched page {page}: {len(items)} active tenders")
            time.sleep(API_RATE_DELAY)
        return all_items

    def fetch_all_results(
        self,
        category: str = "",
        state: str = "",
        max_pages: int = 10,
    ) -> list[dict]:
        """Fetch all pages of tender results."""
        all_items = []
        for page in range(1, max_pages + 1):
            items = self.fetch_tender_results(
                category=category, state=state, page=page
            )
            if not items:
                log.info(f"  No more results at page {page}")
                break
            all_items.extend(items)
            log.info(f"  Fetched page {page}: {len(items)} results")
            time.sleep(API_RATE_DELAY)
        return all_items

    # ── HTTP helper ────────────────────────────────────────
    def _get(self, url: str, params: dict) -> list[dict]:
        try:
            resp = self.session.get(url, params=params, timeout=API_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            # API may return {"data": [...]} or raw list
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("data", data.get("results", data.get("tenders", [])))
            return []
        except requests.exceptions.ConnectionError:
            log.error(f"Cannot connect to API: {url}")
        except requests.exceptions.Timeout:
            log.error(f"API timeout: {url}")
        except requests.exceptions.HTTPError as e:
            log.error(f"API HTTP error: {e}")
        except Exception as e:
            log.error(f"API error: {e}")
        return []


# ── LOCAL FILE LOADER (for testing with sample JSONs) ─────
def load_from_file(filepath: str) -> list[dict]:
    """
    Load tender data from a local JSON file.
    Used for testing without API access.
    """
    import json
    with open(filepath, encoding="utf-8") as f:
        content = f.read().strip()
    # Handle Format 2: multiple root objects (not array)
    if content.startswith("{"):
        content = "[" + content + "]"
    return json.loads(content)

