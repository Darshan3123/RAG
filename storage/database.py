# =========================================================
# storage/database.py
# SQLite storage — dedup, upsert, new-bid detection
# Extended schema with all unified tender format fields
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
    -- Core identity
    document_url        TEXT PRIMARY KEY,
    bid_no              TEXT,
    ra_no               TEXT,
    bid_type            TEXT,
    product_type        TEXT,
    -- Item fields
    full_item_name      TEXT,
    quantity            TEXT,
    category            TEXT,
    sub_category        TEXT,
    product_name        TEXT,
    search_text         TEXT,
    -- Organisation
    department          TEXT,
    authority           TEXT,
    sector              TEXT,
    ownership           TEXT DEFAULT 'Government Departments',
    -- Dates (stored as "DD-MM-YYYY HH:MM:SS" strings)
    start_date          TEXT,
    end_date            TEXT,
    open_date           TEXT,
    -- Money
    estimated_value     TEXT,
    earnest_amount      TEXT,
    doc_cost            TEXT,
    -- Bid meta
    bid_packet_type     TEXT,
    procurement_type    TEXT,
    bidding_type        TEXT DEFAULT 'Tender',
    competition_type    TEXT DEFAULT 'NCB',
    tender_type         TEXT,
    tender_status       TEXT,
    is_corrigendum      INTEGER DEFAULT 0,
    -- Location
    city                TEXT,
    state               TEXT,
    country             TEXT DEFAULT 'India',
    address             TEXT,
    address_pin         TEXT,
    -- Contact
    contact_person      TEXT,
    contact_email       TEXT,
    contact_phone       TEXT,
    -- Document
    corrigendum_url     TEXT,
    document_path       TEXT,
    full_pdf_text       TEXT,
    -- Source
    procurement_source  TEXT,
    -- Tender format fields (JSON serialised)
    tender_record       TEXT,
    -- Metadata
    first_seen          TEXT,
    last_seen           TEXT,
    is_new              INTEGER DEFAULT 1
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
            # Add any new columns that may not exist in older DBs
            self._migrate(conn)
        log.info(f"Database ready: {self.db_path}")

    def _migrate(self, conn):
        """Add new columns to existing DB without dropping data."""
        new_cols = [
            ("category",          "TEXT"),
            ("sub_category",      "TEXT"),
            ("product_name",      "TEXT"),
            ("search_text",       "TEXT"),
            ("authority",         "TEXT"),
            ("sector",            "TEXT"),
            ("ownership",         "TEXT DEFAULT 'Government Departments'"),
            ("open_date",         "TEXT"),
            ("earnest_amount",    "TEXT"),
            ("doc_cost",          "TEXT"),
            ("procurement_type",  "TEXT"),
            ("bidding_type",      "TEXT DEFAULT 'Tender'"),
            ("competition_type",  "TEXT DEFAULT 'NCB'"),
            ("tender_type",       "TEXT"),
            ("tender_status",     "TEXT"),
            ("is_corrigendum",    "INTEGER DEFAULT 0"),
            ("city",              "TEXT"),
            ("state",             "TEXT"),
            ("country",           "TEXT DEFAULT 'India'"),
            ("address",           "TEXT"),
            ("address_pin",       "TEXT"),
            ("contact_person",    "TEXT"),
            ("contact_email",     "TEXT"),
            ("contact_phone",     "TEXT"),
            ("document_path",     "TEXT"),
            ("procurement_source","TEXT"),
            ("tender_record",     "TEXT"),
        ]
        existing = {row[1] for row in conn.execute("PRAGMA table_info(bids)").fetchall()}
        for col, col_type in new_cols:
            if col not in existing:
                try:
                    conn.execute(f"ALTER TABLE bids ADD COLUMN {col} {col_type}")
                    log.info(f"  DB migration: added column '{col}'")
                except Exception as e:
                    log.debug(f"  Migration skip {col}: {e}")
        conn.commit()

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
    def upsert(self, bid: dict, tender_record: dict | None = None) -> bool:
        now = datetime.utcnow().isoformat()
        is_new = not self.exists(bid["document_url"])
        tender_json = json.dumps(tender_record, ensure_ascii=False) if tender_record else ""

        with self._conn() as conn:
            if is_new:
                conn.execute("""
                    INSERT INTO bids (
                        document_url, bid_no, ra_no,
                        bid_type, product_type, full_item_name,
                        quantity, department, authority, sector,
                        category, sub_category, product_name, search_text,
                        start_date, end_date, open_date,
                        estimated_value, earnest_amount, doc_cost,
                        bid_packet_type, procurement_type, bidding_type,
                        competition_type, tender_type, tender_status,
                        is_corrigendum,
                        city, state, country, address, address_pin,
                        contact_person, contact_email, contact_phone,
                        corrigendum_url, document_path, full_pdf_text,
                        procurement_source, tender_record,
                        first_seen, last_seen, is_new
                    ) VALUES (
                        :document_url, :bid_no, :ra_no,
                        :bid_type, :product_type, :full_item_name,
                        :quantity, :department, :authority, :sector,
                        :category, :sub_category, :product_name, :search_text,
                        :start_date, :end_date, :open_date,
                        :estimated_value, :earnest_amount, :doc_cost,
                        :bid_packet_type, :procurement_type, :bidding_type,
                        :competition_type, :tender_type, :tender_status,
                        :is_corrigendum,
                        :city, :state, :country, :address, :address_pin,
                        :contact_person, :contact_email, :contact_phone,
                        :corrigendum_url, :document_path, :full_pdf_text,
                        :procurement_source, :tender_record,
                        :first_seen, :last_seen, 1
                    )
                """, {
                    **bid,
                    "department":        bid.get("department", ""),
                    "authority":         bid.get("authority", ""),
                    "sector":            bid.get("sector", ""),
                    "category":          bid.get("category", ""),
                    "sub_category":      bid.get("sub_category", ""),
                    "product_name":      bid.get("product_name", ""),
                    "search_text":       bid.get("search_text", ""),
                    "open_date":         bid.get("open_date", ""),
                    "earnest_amount":    bid.get("earnest_amount", ""),
                    "doc_cost":          bid.get("doc_cost", ""),
                    "procurement_type":  bid.get("procurement_type", ""),
                    "bidding_type":      bid.get("bidding_type", "Tender"),
                    "competition_type":  bid.get("competition_type", "NCB"),
                    "tender_type":       bid.get("tender_type", "Open Tender"),
                    "tender_status":     bid.get("tender_status", "OPEN"),
                    "is_corrigendum":    1 if bid.get("is_corrigendum") else 0,
                    "city":              bid.get("city", ""),
                    "state":             bid.get("state", ""),
                    "country":           bid.get("country", "India"),
                    "address":           bid.get("address", ""),
                    "address_pin":       bid.get("address_pin", ""),
                    "contact_person":    bid.get("contact_person", ""),
                    "contact_email":     bid.get("contact_email", ""),
                    "contact_phone":     bid.get("contact_phone", ""),
                    "document_path":     bid.get("document_path", ""),
                    "procurement_source": bid.get("procurement_source", "https://gem.gov.in/"),
                    "tender_record":     tender_json,
                    "first_seen":        now,
                    "last_seen":         now,
                })
                log.info(f"  NEW BID saved: {bid.get('bid_no')}")
            else:
                conn.execute("""
                    UPDATE bids
                    SET last_seen = ?, is_new = 0,
                        ra_no = ?, corrigendum_url = ?,
                        tender_status = ?, tender_record = ?
                    WHERE document_url = ?
                """, (
                    now,
                    bid.get("ra_no", ""),
                    bid.get("corrigendum_url", ""),
                    bid.get("tender_status", "OPEN"),
                    tender_json,
                    bid["document_url"],
                ))

        # ── RAG: index into vector store (new bids only) ──
        if is_new:
            try:
                log.info(f"  [database] Starting RAG indexing for {bid.get('bid_no')}...")
                from rag.vector_store import upsert_bid
                upsert_bid(bid)
                log.info(f"  [database] RAG indexing complete")
            except Exception as e:
                log.warning(f"  [database] RAG index failed for "
                            f"{bid.get('bid_no','?')}: {e}", exc_info=True)

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
    # EXPORT JSON — in unified tender format
    # -------------------------------------------------------
    def export_json(self, path: str = JSON_OUT_PATH):
        rows = self.get_all()
        output = []
        for b in rows:
            # If a pre-assembled tender_record is stored, use it directly
            if b.get("tender_record"):
                try:
                    output.append(json.loads(b["tender_record"]))
                    continue
                except Exception:
                    pass
            # Fallback: strip internal fields and export raw row
            b.pop("full_pdf_text", None)
            b.pop("tender_record", None)
            output.append(b)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        log.info(f"JSON exported: {path} ({len(output)} records)")

    # -------------------------------------------------------
    # STATS
    # -------------------------------------------------------
    def stats(self) -> dict:
        with self._conn() as conn:
            total  = conn.execute("SELECT COUNT(*) FROM bids").fetchone()[0]
            new    = conn.execute("SELECT COUNT(*) FROM bids WHERE is_new=1").fetchone()[0]
            runs   = conn.execute("SELECT COUNT(*) FROM run_log").fetchone()[0]
        return {"total": total, "new_this_run": new, "total_runs": runs}
