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
    # ADVANCED SEARCH BY BID NUMBER
    # -------------------------------------------------------
    def advanced_search_bid(self, bid_no: str):
        """Navigate to Advanced Search and fetch a specific bid."""
        url = "https://bidplus.gem.gov.in/advance-search"
        log.info(f"Opening Advanced Search: {url}")
        self.list_page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=120_000,
        )
        sleep_page_load()
        human_mouse_move(self.list_page)
        
        log.info(f"Entering Bid No: {bid_no}")
        
        # Locate the input field explicitly associated with the 'Bid / RA Number' label
        input_box = self.list_page.locator("xpath=//label[contains(text(), 'Bid / RA Number')]/parent::*//input[@type='text']")
        
        if input_box.count() > 0:
            input_box.first.fill(bid_no)
        else:
            # Fallback to the first text input available in the search area
            self.list_page.locator("input[type='text']").first.fill(bid_no)
            
        # UPDATED LOCATOR: Target Bootstrap .btn classes, <a> tags, and <input> tags as well
        search_btn = self.list_page.locator(".btn:has-text('Search'), button:has-text('Search'), input[value*='Search']").first
        search_btn.click()
        
        sleep_filter_click()
        human_mouse_move(self.list_page)
        log.info("Clicked search, waiting for results...")

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
    # DOWNLOAD PDF  (with retry)
    # -------------------------------------------------------
    def download_pdf(
        self,
        document_url: str,
        save_dir: str = DOWNLOAD_DIR,
        filename: str | None = None,
        retries: int = 3
    ) -> str | None:
        """
        Download a PDF file from a given URL using Playwright download event listener.
        
        Args:
            document_url (str): Target PDF download link.
            save_dir (str): Target destination directory (defaults to DOWNLOAD_DIR).
            filename (str | None): Custom target filename. If None, uses suggested filename.
            retries (int): Retry attempts on download failure.
            
        Returns:
            str | None: Absolute file path of downloaded PDF or None on failure.
        """
        os.makedirs(save_dir, exist_ok=True)
        for attempt in range(1, retries + 1):
            try:
                with self.dl_page.expect_download(
                    timeout=60_000
                ) as dl_info:
                    self.dl_page.evaluate(
                        f'window.location.href = "{document_url}"'
                    )
                download = dl_info.value
                target_filename = filename or download.suggested_filename or "bid.pdf"
                path     = os.path.join(save_dir, target_filename)
                download.save_as(path)
                sleep_pdf_download()
                log.debug(f"Downloaded: {path}")
                return path
            except Exception as e:
                log.warning(
                    f"Download attempt {attempt}/{retries} "
                    f"failed for {document_url}: {e}"
                )
                time.sleep(5 * attempt)
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
    # Returns (document_url, ra_url, corrigendum_url)
    # -------------------------------------------------------
    def extract_card_links(self, card) -> tuple[str, str, str]:
        from config.settings import GEM_BASE_URL
        document_url    = ""
        ra_url          = ""
        corrigendum_url = ""
        
        links = card.locator("a")
        for j in range(links.count()):
            try:
                href      = links.nth(j).get_attribute("href") or ""
                link_text = links.nth(j).inner_text().strip()
                
                if not href:
                    continue
                
                # Extract main bid PDF URL
                if "showbiddocument" in href.lower():
                    document_url = (
                        GEM_BASE_URL + "/" + href.lstrip("/")
                    )
                # Extract RA PDF URL
                elif "showradocumentpdf" in href.lower():
                    ra_url = (
                        GEM_BASE_URL + "/" + href.lstrip("/")
                    )
                
                # Extract Corrigendum URL
                if "corrigendum" in link_text.lower():
                    corrigendum_url = (
                        GEM_BASE_URL + "/" + href.lstrip("/")
                    )
            except Exception:
                pass
                
        return document_url, ra_url, corrigendum_url