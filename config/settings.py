# =========================================================
# config/settings.py
# Central config — change values here, nothing else needed
# =========================================================
import os

# ---------------------------------------------------------
# SCHEDULER
# ---------------------------------------------------------
SCRAPE_INTERVAL_MINUTES = 60        # run every 60 min
MAX_RETRIES_PER_BID     = 3         # retry failed bids
RETRY_DELAY_SECONDS     = 10        # wait between retries

# ---------------------------------------------------------
# ANTI-BOT  (human-like delays in seconds)
# ---------------------------------------------------------
PAGE_LOAD_WAIT          = (4, 8)    # random range
BETWEEN_CARDS_WAIT      = (1, 3)
BETWEEN_PAGES_WAIT      = (3, 6)
FILTER_CLICK_WAIT       = (3, 6)
PDF_DOWNLOAD_WAIT       = (2, 4)

# User-Agent pool — rotated per browser launch
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# Viewport pool — rotated per browser launch
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
]

# ---------------------------------------------------------
# SCRAPER TARGETS
# ---------------------------------------------------------
GEM_BASE_URL   = "https://bidplus.gem.gov.in"
GEM_ALL_BIDS   = f"{GEM_BASE_URL}/all-bids"

BID_TYPES = [
    "Product Bid/RAs",
    "Service Bid/RAs",
    "Bid To RAs",
    "Product Custom Bid/RAs",
    "BOQ Bids",
    "Rate Contract Bids",
    "Global Tender",
    "Limited Tender",
    "Single Tender",
]

# How many bids to collect per type per run
TARGET_PER_TYPE  = 10
MAX_EMPTY_PAGES  = 5

# ---------------------------------------------------------
# PATHS
# ---------------------------------------------------------
BASE_DIR      = os.path.dirname(os.path.dirname(__file__))
DOWNLOAD_DIR  = os.path.join(BASE_DIR, "downloads")
LOG_DIR       = os.path.join(BASE_DIR, "logs")
DB_PATH       = os.path.join(BASE_DIR, "storage", "gem_bids.db")
JSON_OUT_PATH = os.path.join(BASE_DIR, "storage", "gem_bids.json")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(LOG_DIR,      exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "storage"), exist_ok=True)

# ---------------------------------------------------------
# TESSERACT (Windows path — ignored on Linux)
# ---------------------------------------------------------
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ---------------------------------------------------------
# RAG SETTINGS
# ---------------------------------------------------------
# Embedding model — runs fully LOCAL, no API key needed
# Options: "all-MiniLM-L6-v2" (fast, 384-dim)
#          "all-mpnet-base-v2" (slower, better, 768-dim)
RAG_EMBEDDING_MODEL  = "all-MiniLM-L6-v2"

# ChromaDB persistent path
CHROMA_DIR           = os.path.join(BASE_DIR, "storage", "chroma_db")

# Collection name inside ChromaDB
CHROMA_COLLECTION    = "gem_bids"

# How many chunks to retrieve per query
RAG_TOP_K            = 5

# Max characters per chunk when splitting long PDF text
RAG_CHUNK_SIZE       = 800
RAG_CHUNK_OVERLAP    = 100

# LLM for answering — set to "" to disable LLM, use retrieval only
# Options: "openai" | "ollama" | ""  (retrieval-only)
RAG_LLM_PROVIDER     = "ollama"    # change to "openai" if you have a key

# OpenAI settings (used only if RAG_LLM_PROVIDER = "openai")
OPENAI_API_KEY       = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL         = "gpt-4o-mini"

# Ollama settings (used only if RAG_LLM_PROVIDER = "ollama")
OLLAMA_BASE_URL      = "http://localhost:11434"
OLLAMA_MODEL         = "llama3"

os.makedirs(CHROMA_DIR, exist_ok=True)

# ---------------------------------------------------------
# PRODUCT TYPE MAP  (bid_type → clean label)
# ---------------------------------------------------------
PRODUCT_TYPE_MAP = {
    "Product Bid/RAs":        "Product",
    "Service Bid/RAs":        "Service",
    "Bid To RAs":             "Bid To RA",
    "Product Custom Bid/RAs": "Product",
    "BOQ Bids":               "BOQ",
    "Rate Contract Bids":     "Rate Contract",
    "Global Tender":          "Global Tender",
    "Limited Tender":         "Limited Tender",
    "Single Tender":          "Single Tender",
}
