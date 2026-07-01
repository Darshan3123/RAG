# =========================================================
# scraper/core/browser.py
# Playwright browser manager — stealth, retry, context mgr
# =========================================================
import os
import time
from playwright.sync_api import sync_playwright, Page
from shared.config.settings import DOWNLOAD_DIR, GEM_ALL_BIDS
from shared.utils.antibot import (
    stealth_launch_options,
    stealth_context_options,
    human_mouse_move,
    sleep_page_load,
    sleep_filter_click,
    sleep_between_pages,
    sleep_pdf_download,
    sleep_between_cards,
)
from shared.utils.logger import get_logger

log = get_logger("browser")


class GemBrowser:
    """
    Manages a single Playwright browser session.
    Use as a context manager:

        with GemBrowser() as browser:
            browser.open_gem()
            ...
    """

    def __init__(self):
        self._pw       = None
        self._browser  = None
        self._context  = None
        self.list_page: Page = None
        self.dl_page:   Page = None

    def __enter__(self):
        self._pw      = sync_playwright().start()
        self._browser = self._pw.chromium.launch(**stealth_launch_options())
        self._context = self._browser.new_context(**stealth_context_options())
        self._context.set_default_timeout(60_000)
        self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        """)
        self.list_page = self._context.new_page()
        self.dl_page   = self._context.new_page()
        log.info("Browser launched (stealth mode)")
        return self

    def __exit__(self, *_):
        try:
            self._context.close()
            self._browser.close()
            self._pw.stop()
            log.info("Browser closed")
        except Exception as e:
            log.warning(f"Browser close error: {e}")

    def open_gem(self):
        log.info(f"Opening: {GEM_ALL_BIDS}")
        self.list_page.goto(GEM_ALL_BIDS, wait_until="domcontentloaded", timeout=120_000)
        sleep_page_load()
        human_mouse_move(self.list_page)
        log.info("GeM listing page loaded")

    def reset_filters(self):
        try:
            btn = self.list_page.locator("text=Reset")
            if btn.count() > 0:
                btn.first.click()
                sleep_filter_click()
        except Exception as e:
            log.debug(f"Reset filter: {e}")

    def select_bid_type(self, bid_type_name: str):
        log.info(f"Selecting filter: {bid_type_name}")
        self.list_page.locator(f"label:has-text('{bid_type_name}')").click()
        sleep_filter_click()
        human_mouse_move(self.list_page)

    def select_ongoing_bids(self):
        log.info("Selecting filter: Ongoing Bids/RA")
        try:
            self.list_page.locator("label:has-text('Ongoing Bids/RA')").click()
            sleep_filter_click()
            human_mouse_move(self.list_page)
        except Exception as e:
            log.warning(f"Could not select Ongoing Bids/RA filter: {e}")

    def download_pdf(self, document_url: str, retries: int = 3,
                     bid_type: str = "") -> str | None:
        import re
        import requests

        def _safe_folder(bid_type_name: str) -> str:
            """Convert bid type name to a safe folder name."""
            name = bid_type_name.strip()
            # Replace slashes and spaces with underscores, strip special chars
            name = re.sub(r"[/\\]", "_", name)
            name = re.sub(r"\s+", "_", name)
            name = re.sub(r"[^\w\-]", "", name)
            return name or "Other"

        def _filename_from_url(url: str) -> str:
            name = url.rstrip("/").split("/")[-1].split("?")[0]
            if not name.lower().endswith(".pdf"):
                name += ".pdf"
            return re.sub(r"[^\w\-.]", "_", name) or "bid.pdf"

        def _filename_from_headers(resp, fallback: str) -> str:
            cd = resp.headers.get("Content-Disposition", "")
            if cd:
                m = re.search(r'filename[^;=\n]*=(["\']?)(.+?)\1(?:;|$)', cd)
                if m:
                    fn = m.group(2).strip()
                    return fn if fn.lower().endswith(".pdf") else fn + ".pdf"
            return fallback

        # ── Determine save directory ──
        if bid_type:
            save_dir = os.path.join(DOWNLOAD_DIR, _safe_folder(bid_type))
        else:
            save_dir = DOWNLOAD_DIR
        os.makedirs(save_dir, exist_ok=True)

        for attempt in range(1, retries + 1):
            log.info(f"  PDF download attempt {attempt}/{retries}: {document_url}")

            # Strategy 1: direct HTTP GET
            try:
                cookies = {c["name"]: c["value"] for c in self._context.cookies()}
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Referer": "https://bidplus.gem.gov.in/",
                    "Accept": "application/pdf,*/*",
                }
                resp = requests.get(document_url, cookies=cookies, headers=headers,
                                    timeout=(20, 60), stream=True)
                ct = resp.headers.get("Content-Type", "")
                if resp.status_code == 200 and "pdf" in ct.lower():
                    filename = _filename_from_headers(resp, _filename_from_url(document_url))
                    path = os.path.join(save_dir, filename)
                    with open(path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                    resp.close()
                    sleep_pdf_download()
                    log.info(f"  Downloaded OK (HTTP): {filename}")
                    return path
                resp.close()
            except requests.exceptions.Timeout:
                log.warning(f"  HTTP GET timed out")
            except Exception as e:
                log.warning(f"  HTTP GET failed: {e}")

            # Strategy 2: Playwright page.goto()
            try:
                response = self.dl_page.goto(document_url, wait_until="load", timeout=60_000)
                if response and response.status == 200:
                    ct = response.headers.get("content-type", "")
                    if "pdf" in ct.lower():
                        body = response.body()
                        filename = _filename_from_url(document_url)
                        path = os.path.join(save_dir, filename)
                        with open(path, "wb") as f:
                            f.write(body)
                        sleep_pdf_download()
                        log.info(f"  Downloaded OK (goto): {filename}")
                        return path
            except Exception as e:
                log.warning(f"  Playwright goto failed: {e}")

            time.sleep(3 * attempt)

        log.error(f"  All {retries} download attempts failed: {document_url}")
        return None

    def go_next_page(self) -> bool:
        try:
            btn = self.list_page.locator("text=Next")
            if btn.count() == 0:
                return False
            btn.first.click()
            sleep_between_pages()
            human_mouse_move(self.list_page)
            return True
        except Exception as e:
            log.debug(f"Pagination ended: {e}")
            return False

    def get_cards(self):
        return self.list_page.locator("div.card")

    def wait_for_cards(self, timeout_ms: int = 15_000):
        try:
            self.list_page.wait_for_selector("div.card", state="attached", timeout=timeout_ms)
            self.list_page.wait_for_function(
                """() => {
                    const cards = document.querySelectorAll('div.card');
                    if (!cards.length) return false;
                    return Array.from(cards).some(c =>
                        c.querySelector('[data-content], [data-original-title]'));
                }""",
                timeout=timeout_ms,
            )
        except Exception as e:
            log.debug(f"wait_for_cards: {e}")

    def extract_card_links(self, card) -> tuple[str, str, str]:
        from shared.config.settings import GEM_BASE_URL
        document_url    = ""
        corrigendum_url = ""
        ra_url          = ""
        links = card.locator("a")
        for j in range(links.count()):
            try:
                href      = links.nth(j).get_attribute("href") or ""
                link_text = links.nth(j).inner_text().strip()
                if not href:
                    continue
                if "showbiddocument" in href.lower():
                    document_url = GEM_BASE_URL + "/" + href.lstrip("/")
                if "corrigendum" in link_text.lower():
                    corrigendum_url = GEM_BASE_URL + "/" + href.lstrip("/")
                if "showradocument" in href.lower():
                    ra_url = GEM_BASE_URL + "/" + href.lstrip("/")
            except Exception:
                pass
        return document_url, corrigendum_url, ra_url
