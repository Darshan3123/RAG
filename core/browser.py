# =========================================================
# core/browser.py
# Playwright browser manager — stealth, retry, context mgr
# =========================================================
import os
import time
from playwright.sync_api import sync_playwright, Page
from config.settings import DOWNLOAD_DIR, GEM_ALL_BIDS
from utils.antibot import (
    stealth_launch_options,
    stealth_context_options,
    human_mouse_move,
    sleep_page_load,
    sleep_filter_click,
    sleep_between_pages,
    sleep_pdf_download,
    sleep_between_cards,
)
from utils.logger import get_logger

log = get_logger("browser")


class GemBrowser:
    """
    Manages a single Playwright browser session.
    Call as a context manager:

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

    # -------------------------------------------------------
    # CONTEXT MANAGER
    # -------------------------------------------------------
    def __enter__(self):
        self._pw      = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            **stealth_launch_options()
        )
        self._context = self._browser.new_context(
            **stealth_context_options()
        )
        self._context.set_default_timeout(60_000)

        # Inject stealth JS — hides webdriver flag
        self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
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

    # -------------------------------------------------------
    # OPEN GEM LISTING PAGE
    # -------------------------------------------------------
    def open_gem(self):
        log.info(f"Opening: {GEM_ALL_BIDS}")
        self.list_page.goto(
            GEM_ALL_BIDS,
            wait_until="domcontentloaded",
            timeout=120_000,
        )
        sleep_page_load()
        human_mouse_move(self.list_page)
        log.info("GeM listing page loaded")

    # -------------------------------------------------------
    # RESET FILTERS
    # -------------------------------------------------------
    def reset_filters(self):
        try:
            btn = self.list_page.locator("text=Reset")
            if btn.count() > 0:
                btn.first.click()
                sleep_filter_click()
                log.debug("Filters reset")
        except Exception as e:
            log.debug(f"Reset filter: {e}")

    # -------------------------------------------------------
    # SELECT BID TYPE CHECKBOX
    # -------------------------------------------------------
    def select_bid_type(self, bid_type_name: str):
        log.info(f"Selecting filter: {bid_type_name}")
        label = self.list_page.locator(
            f"label:has-text('{bid_type_name}')"
        )
        label.click()
        sleep_filter_click()
        human_mouse_move(self.list_page)

    # -------------------------------------------------------
    # SELECT "ONGOING BIDS/RA" FILTER
    # Only scrape active/open bids, not completed ones
    # -------------------------------------------------------
    def select_ongoing_bids(self):
        """Click the 'Ongoing Bids/RA' checkbox to filter only active bids"""
        log.info("Selecting filter: Ongoing Bids/RA")
        try:
            label = self.list_page.locator(
                "label:has-text('Ongoing Bids/RA')"
            )
            label.click()
            sleep_filter_click()
            human_mouse_move(self.list_page)
            log.debug("Ongoing Bids/RA filter applied")
        except Exception as e:
            log.warning(f"Could not select Ongoing Bids/RA filter: {e}")

    # -------------------------------------------------------
    # DOWNLOAD PDF  (with retry + verbose logging)
    # Strategy:
    #   1. Try direct HTTP GET (requests) with strict timeouts.
    #      - connect+first-byte: 20s
    #      - total body read: 60s via a socket-level deadline
    #   2. Fall back to Playwright page.goto() which returns
    #      the response body directly — no download-event needed.
    # -------------------------------------------------------
    def download_pdf(
        self,
        document_url: str,
        retries: int = 3
    ) -> str | None:
        import re
        import requests

        def _filename_from_url(url: str) -> str:
            name = url.rstrip("/").split("/")[-1].split("?")[0]
            if not name.lower().endswith(".pdf"):
                name += ".pdf"
            name = re.sub(r"[^\w\-.]", "_", name)
            return name or "bid.pdf"

        def _filename_from_headers(resp, fallback: str) -> str:
            cd = resp.headers.get("Content-Disposition", "")
            if cd:
                m = re.search(r'filename[^;=\n]*=(["\']?)(.+?)\1(?:;|$)', cd)
                if m:
                    fn = m.group(2).strip()
                    if not fn.lower().endswith(".pdf"):
                        fn += ".pdf"
                    return fn
            return fallback

        for attempt in range(1, retries + 1):
            log.info(f"  PDF download attempt {attempt}/{retries}: {document_url}")

            # ── Strategy 1: direct HTTP GET ──
            try:
                log.info(f"  [attempt {attempt}] Trying HTTP GET...")
                cookies = {
                    c["name"]: c["value"]
                    for c in self._context.cookies()
                }
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Referer": "https://bidplus.gem.gov.in/",
                    "Accept": "application/pdf,*/*",
                }
                # timeout=(connect_timeout, read_timeout)
                resp = requests.get(
                    document_url,
                    cookies=cookies,
                    headers=headers,
                    timeout=(20, 60),
                    stream=True,
                )
                log.info(
                    f"  [attempt {attempt}] HTTP status={resp.status_code} "
                    f"content-type='{resp.headers.get('Content-Type', '')}'"
                )
                content_type = resp.headers.get("Content-Type", "")
                if resp.status_code == 200 and "pdf" in content_type.lower():
                    filename = _filename_from_headers(resp, _filename_from_url(document_url))
                    path = os.path.join(DOWNLOAD_DIR, filename)
                    log.info(f"  [attempt {attempt}] Writing PDF to {filename}...")
                    with open(path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                    resp.close()
                    sleep_pdf_download()
                    log.info(f"  [attempt {attempt}] Downloaded OK (HTTP): {filename}")
                    return path
                else:
                    resp.close()
                    log.info(
                        f"  [attempt {attempt}] HTTP response not a PDF "
                        f"(status={resp.status_code}, ct='{content_type}') "
                        f"— trying browser fallback"
                    )
            except requests.exceptions.Timeout:
                log.warning(f"  [attempt {attempt}] HTTP GET timed out for {document_url}")
            except Exception as e:
                log.warning(f"  [attempt {attempt}] HTTP GET failed: {e}")

            # ── Strategy 2: Playwright page.goto() ──
            # page.goto returns response object; we read its body directly.
            # This avoids expect_download() which only fires on
            # Content-Disposition: attachment.
            try:
                log.info(f"  [attempt {attempt}] Trying Playwright goto()...")
                response = self.dl_page.goto(
                    document_url,
                    wait_until="load",
                    timeout=60_000,
                )
                if response and response.status == 200:
                    ct = response.headers.get("content-type", "")
                    log.info(
                        f"  [attempt {attempt}] Playwright goto status=200 "
                        f"content-type='{ct}'"
                    )
                    if "pdf" in ct.lower():
                        body = response.body()
                        filename = _filename_from_url(document_url)
                        path = os.path.join(DOWNLOAD_DIR, filename)
                        with open(path, "wb") as f:
                            f.write(body)
                        sleep_pdf_download()
                        log.info(f"  [attempt {attempt}] Downloaded OK (goto): {filename}")
                        return path
                    else:
                        log.warning(
                            f"  [attempt {attempt}] Playwright goto: "
                            f"not a PDF content-type='{ct}'"
                        )
                else:
                    status = response.status if response else "no response"
                    log.warning(
                        f"  [attempt {attempt}] Playwright goto failed: "
                        f"status={status}"
                    )
            except Exception as e:
                log.warning(
                    f"  [attempt {attempt}] Playwright goto failed: {e}"
                )

            log.warning(
                f"  Attempt {attempt}/{retries} exhausted for {document_url}"
            )
            time.sleep(3 * attempt)

        log.error(f"  All {retries} download attempts failed: {document_url}")
        return None

    # -------------------------------------------------------
    # CLICK NEXT PAGE
    # Returns False when no more pages
    # -------------------------------------------------------
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

    # -------------------------------------------------------
    # GET CARDS ON CURRENT PAGE
    # -------------------------------------------------------
    def get_cards(self):
        return self.list_page.locator("div.card")

    # -------------------------------------------------------
    # WAIT FOR CARDS TO BE PRESENT
    # Bootstrap popovers populate `data-content` only after
    # the card list finishes rendering — give the DOM time.
    # -------------------------------------------------------
    def wait_for_cards(self, timeout_ms: int = 15_000):
        try:
            self.list_page.wait_for_selector(
                "div.card", state="attached", timeout=timeout_ms
            )
            # Make sure the popover trigger attribute is filled in.
            # On some pages the framework injects `data-content` a
            # tick after the card appears.
            self.list_page.wait_for_function(
                """() => {
                    const cards = document.querySelectorAll('div.card');
                    if (!cards.length) return false;
                    const hasPopover = Array.from(cards).some(c =>
                        c.querySelector('[data-content], [data-original-title]'));
                    return hasPopover;
                }""",
                timeout=timeout_ms,
            )
        except Exception as e:
            log.debug(f"wait_for_cards: {e}")

    # -------------------------------------------------------
    # EXTRACT LINKS FROM A CARD
    # Returns (document_url, corrigendum_url)
    # -------------------------------------------------------
    def extract_card_links(self, card) -> tuple[str, str]:
        from config.settings import GEM_BASE_URL
        document_url    = ""
        corrigendum_url = ""
        links = card.locator("a")
        for j in range(links.count()):
            try:
                href      = links.nth(j).get_attribute("href") or ""
                link_text = links.nth(j).inner_text().strip()
                if not href:
                    continue
                if "showbiddocument" in href.lower():
                    document_url = (
                        GEM_BASE_URL + "/" + href.lstrip("/")
                    )
                if "corrigendum" in link_text.lower():
                    corrigendum_url = (
                        GEM_BASE_URL + "/" + href.lstrip("/")
                    )
            except Exception:
                pass
        return document_url, corrigendum_url