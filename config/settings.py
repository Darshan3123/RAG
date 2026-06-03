# =========================================================
# config/settings.py
# All configuration is loaded from the .env file at the
# project root.  Change values there — not here.
# =========================================================
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (one level above this file)
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Propagate HF_TOKEN to the environment so huggingface_hub picks it up
_hf_token = os.getenv("HF_TOKEN", "")
if _hf_token:
    os.environ["HF_TOKEN"] = _hf_token
    os.environ["HUGGING_FACE_HUB_TOKEN"] = _hf_token  # legacy key


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------
def _int(key: str, default: int) -> int:
    return int(os.getenv(key, default))

def _float(key: str, default: float) -> float:
    return float(os.getenv(key, default))

def _str(key: str, default: str = "") -> str:
    return os.getenv(key, default)

def _path(key: str, default: str) -> str:
    """Resolve a path relative to BASE_DIR unless it's absolute."""
    raw = os.getenv(key, default)
    p   = Path(raw)
    return str(p if p.is_absolute() else BASE_DIR / p)


# ---------------------------------------------------------
# SCHEDULER
# ---------------------------------------------------------
SCRAPE_INTERVAL_MINUTES = _int("SCRAPE_INTERVAL_MINUTES", 60)
MAX_RETRIES_PER_BID     = _int("MAX_RETRIES_PER_BID", 3)
RETRY_DELAY_SECONDS     = _int("RETRY_DELAY_SECONDS", 10)

# ---------------------------------------------------------
# ANTI-BOT  (human-like delays in seconds)
# ---------------------------------------------------------
PAGE_LOAD_WAIT     = (_float("PAGE_LOAD_WAIT_MIN",     4), _float("PAGE_LOAD_WAIT_MAX",     8))
BETWEEN_CARDS_WAIT = (_float("BETWEEN_CARDS_WAIT_MIN", 1), _float("BETWEEN_CARDS_WAIT_MAX", 3))
BETWEEN_PAGES_WAIT = (_float("BETWEEN_PAGES_WAIT_MIN", 3), _float("BETWEEN_PAGES_WAIT_MAX", 6))
FILTER_CLICK_WAIT  = (_float("FILTER_CLICK_WAIT_MIN",  3), _float("FILTER_CLICK_WAIT_MAX",  6))
PDF_DOWNLOAD_WAIT  = (_float("PDF_DOWNLOAD_WAIT_MIN",  2), _float("PDF_DOWNLOAD_WAIT_MAX",  4))

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
GEM_BASE_URL = _str("GEM_BASE_URL", "https://bidplus.gem.gov.in")
GEM_ALL_BIDS = f"{GEM_BASE_URL}/all-bids"

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

TARGET_PER_TYPE = _int("TARGET_PER_TYPE", 10)
MAX_EMPTY_PAGES = _int("MAX_EMPTY_PAGES", 5)

# ---------------------------------------------------------
# PATHS
# ---------------------------------------------------------
DOWNLOAD_DIR  = _path("DOWNLOAD_DIR",  "downloads")
LOG_DIR       = _path("LOG_DIR",       "logs")
DB_PATH       = _path("DB_PATH",       "storage/gem_bids.db")
JSON_OUT_PATH = _path("JSON_OUT_PATH", "storage/gem_bids.json")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(LOG_DIR,      exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# ---------------------------------------------------------
# TESSERACT  (Windows path — ignored on Linux/Mac)
# ---------------------------------------------------------
TESSERACT_CMD = _str(
    "TESSERACT_CMD",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

# ---------------------------------------------------------
# RAG SETTINGS
# ---------------------------------------------------------
# Embedding model.  Recommended for English bid text:
#   BAAI/bge-base-en-v1.5    (best quality, ~110M params)
#   BAAI/bge-small-en-v1.5   (faster, lower memory)
#   all-MiniLM-L6-v2         (legacy, fastest, lowest quality)
RAG_EMBEDDING_MODEL = _str("RAG_EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
CHROMA_DIR          = _path("CHROMA_DIR", "storage/chroma_db")
CHROMA_COLLECTION   = _str("CHROMA_COLLECTION", "gem_bids")
RAG_TOP_K           = _int("RAG_TOP_K", 5)
RAG_CHUNK_SIZE      = _int("RAG_CHUNK_SIZE", 800)
RAG_CHUNK_OVERLAP   = _int("RAG_CHUNK_OVERLAP", 100)

# Hybrid retrieval
RAG_FETCH_K       = _int("RAG_FETCH_K", 40)      # chunks fetched per leg
RAG_DENSE_WEIGHT  = _float("RAG_DENSE_WEIGHT", 0.6)
RAG_BM25_WEIGHT   = _float("RAG_BM25_WEIGHT", 0.4)

# Cross-encoder reranker.  Single biggest score booster.
# Default model is small + CPU-friendly.
RAG_USE_RERANKER  = _str("RAG_USE_RERANKER", "true").lower() in ("1", "true", "yes", "on")
RAG_RERANKER_MODEL = _str("RAG_RERANKER_MODEL", "BAAI/bge-reranker-base")

RAG_LLM_PROVIDER = _str("RAG_LLM_PROVIDER", "ollama")

# OpenAI  (used only when RAG_LLM_PROVIDER=openai)
OPENAI_API_KEY = _str("OPENAI_API_KEY", "")
OPENAI_MODEL   = _str("OPENAI_MODEL",   "gpt-4o-mini")

# Ollama  (used only when RAG_LLM_PROVIDER=ollama)
OLLAMA_BASE_URL = _str("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = _str("OLLAMA_MODEL",    "llama3")

os.makedirs(CHROMA_DIR, exist_ok=True)

# ---------------------------------------------------------
# TENDER API  (external tender data — active + awarded)
# ---------------------------------------------------------
TENDER_API_BASE_URL   = _str("TENDER_API_BASE_URL", "")
TENDER_API_KEY        = _str("TENDER_API_KEY", "")
TENDER_API_TIMEOUT    = _int("TENDER_API_TIMEOUT", 30)
TENDER_API_PAGE_SIZE  = _int("TENDER_API_PAGE_SIZE", 50)
TENDER_API_RATE_DELAY = _float("TENDER_API_RATE_DELAY", 1.0)
TENDER_DB_PATH        = _path("TENDER_DB_PATH", "storage/tenders.db")
TENDER_JSON_PATH      = _path("TENDER_JSON_PATH", "storage/tenders.json")

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