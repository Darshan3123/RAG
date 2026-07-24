# =========================================================
# storage/database.py
# SQLite storage — dedup, upsert, new-bid detection
# =========================================================
import sqlite3
import json
import os
from datetime import datetime
from config.settings import DB_PATH, JSON_OUT_PATH
from utils.logger import get_logger

log = get_logger("database")


# ---------------------------------------------------------
# SCHEMA
# ---------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS bids (
    document_url     TEXT PRIMARY KEY,
    bid_no           TEXT,
    ra_no            TEXT,
    bid_type         TEXT,
    product_type     TEXT,
    full_item_name   TEXT,
    quantity         TEXT,
    department       TEXT,
    start_date       TEXT,
    end_date         TEXT,
    estimated_value  TEXT,
    bid_packet_type  TEXT,
    corrigendum_url  TEXT,
    pdf_hyperlinks   TEXT DEFAULT '[]',
    full_pdf_text    TEXT,
    first_seen       TEXT,
    last_seen        TEXT,
    is_new           INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS run_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at       TEXT,
    bid_type     TEXT,
    scraped      INTEGER,
    new_bids     INTEGER,
    errors       INTEGER,
    duration_sec REAL
);
"""


# ---------------------------------------------------------
# DB CLASS
# ---------------------------------------------------------
class BidDatabase:

    def __init__(self, db_path: str = DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(bids)").fetchall()]
            if "pdf_hyperlinks" not in cols:
                conn.execute("ALTER TABLE bids ADD COLUMN pdf_hyperlinks TEXT DEFAULT '[]'")
        log.info(f"Database ready: {self.db_path}")

    # -------------------------------------------------------
    # CHECK IF BID EXISTS (deduplication)
    # -------------------------------------------------------
    def exists(self, document_url: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM bids WHERE document_url = ?",
                (document_url,)
            ).fetchone()
        return row is not None

    # -------------------------------------------------------
    # UPSERT — insert new, or update last_seen + is_new=0
    # Returns True if this is a NEW bid
    # -------------------------------------------------------
    def upsert(self, bid: dict) -> bool:
        now = datetime.utcnow().isoformat()
        is_new = not self.exists(bid["document_url"])
        hyperlinks_val = bid.get("pdf_hyperlinks", "[]") or "[]"

        with self._conn() as conn:
            if is_new:
                conn.execute("""
                    INSERT INTO bids (
                        document_url, bid_no, ra_no,
                        bid_type, product_type, full_item_name,
                        quantity, department,
                        start_date, end_date,
                        estimated_value, bid_packet_type,
                        corrigendum_url, pdf_hyperlinks, full_pdf_text,
                        first_seen, last_seen, is_new
                    ) VALUES (
                        :document_url, :bid_no, :ra_no,
                        :bid_type, :product_type, :full_item_name,
                        :quantity, :department,
                        :start_date, :end_date,
                        :estimated_value, :bid_packet_type,
                        :corrigendum_url, :pdf_hyperlinks, :full_pdf_text,
                        :first_seen, :last_seen, 1
                    )
                """, {**bid, "pdf_hyperlinks": hyperlinks_val, "first_seen": now, "last_seen": now})
                log.info(f"  NEW BID saved: {bid.get('bid_no')}")
            else:
                conn.execute("""
                    UPDATE bids
                    SET last_seen = ?, is_new = 0,
                        ra_no = ?, corrigendum_url = ?,
                        pdf_hyperlinks = ?
                    WHERE document_url = ?
                """, (
                    now,
                    bid.get("ra_no", ""),
                    bid.get("corrigendum_url", ""),
                    hyperlinks_val,
                    bid["document_url"],
                ))

        # ── RAG: index into vector store (new bids only) ──
        if is_new:
            try:
                from rag.vector_store import upsert_bid
                upsert_bid(bid)
            except Exception as e:
                log.warning(f"  RAG index failed for "
                            f"{bid.get('bid_no','?')}: {e}")

        return is_new

    # -------------------------------------------------------
    # GET ALL BIDS (for JSON export)
    # -------------------------------------------------------
    def get_all(self) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM bids ORDER BY first_seen DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------
    # GET ONLY NEW BIDS (since last run)
    # -------------------------------------------------------
    def get_new_bids(self) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM bids WHERE is_new = 1"
                " ORDER BY first_seen DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------
    # MARK ALL AS NOT-NEW (call after notifying)
    # -------------------------------------------------------
    def mark_all_seen(self):
        with self._conn() as conn:
            conn.execute("UPDATE bids SET is_new = 0")

    # -------------------------------------------------------
    # LOG A RUN
    # -------------------------------------------------------
    def log_run(
        self, bid_type: str,
        scraped: int, new_bids: int,
        errors: int, duration: float
    ):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO run_log
                  (run_at, bid_type, scraped, new_bids, errors, duration_sec)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.utcnow().isoformat(),
                bid_type, scraped, new_bids, errors, duration
            ))

    # -------------------------------------------------------
    # EXPORT JSON
    # -------------------------------------------------------
    def export_json(self, path: str = JSON_OUT_PATH):
        bids = self.get_all()
        # strip full_pdf_text from JSON export (too large)
        for b in bids:
            b.pop("full_pdf_text", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bids, f, ensure_ascii=False, indent=2)
        log.info(f"JSON exported: {path} ({len(bids)} records)")

    # -------------------------------------------------------
    # STATS
    # -------------------------------------------------------
    def stats(self) -> dict:
        with self._conn() as conn:
            total  = conn.execute("SELECT COUNT(*) FROM bids").fetchone()[0]
            new    = conn.execute("SELECT COUNT(*) FROM bids WHERE is_new=1").fetchone()[0]
            runs   = conn.execute("SELECT COUNT(*) FROM run_log").fetchone()[0]
        return {"total": total, "new_this_run": new, "total_runs": runs}
