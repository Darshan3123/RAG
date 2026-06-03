# =========================================================
# tender_database.py
# SQLite storage for API-sourced tenders (both formats)
# Separate from gem_bids.db — different schema
# =========================================================
from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime
from config.settings import TENDER_DB_PATH as _DEFAULT_DB_PATH, TENDER_JSON_PATH as _DEFAULT_JSON_PATH
from utils.logger import get_logger

log = get_logger("tender_database")

TENDER_DB_PATH = _DEFAULT_DB_PATH


CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS tenders (
    tender_id           TEXT PRIMARY KEY,
    tender_no           TEXT,
    tender_reference_id TEXT,
    status              TEXT,    -- OPEN | AOC
    platform            TEXT,
    source_name         TEXT,
    source_url          TEXT,
    tender_type         TEXT,
    procurement_type    TEXT,
    bidding_type        TEXT,
    competition_type    TEXT,
    category            TEXT,
    sub_category        TEXT,
    product_name        TEXT,
    sector              TEXT,
    authority           TEXT,
    ownership           TEXT,
    city                TEXT,
    state               TEXT,
    country             TEXT,
    address             TEXT,
    address_pin         TEXT,
    contact_person      TEXT,
    contact_email       TEXT,
    contact_phone       TEXT,
    tender_summary      TEXT,
    work_desc           TEXT,
    search_text         TEXT,
    is_corrigendum      TEXT,
    tender_value        TEXT,
    doc_cost            TEXT,
    earnest_amount      TEXT,
    pub_date            TEXT,
    enter_date          TEXT,
    due_date            TEXT,
    open_date           TEXT,
    document_urls       TEXT,    -- JSON array of URLs
    -- Result-only fields
    contract_date       TEXT,
    contract_value      TEXT,
    completion_date     TEXT,
    winner_name         TEXT,
    winner_bid          TEXT,
    all_bidders         TEXT,    -- JSON array
    -- Metadata
    first_seen          TEXT,
    last_seen           TEXT,
    is_new              INTEGER DEFAULT 1
)
"""

CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS tender_runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at     TEXT,
    total      INTEGER,
    new_count  INTEGER,
    source     TEXT
)
"""


class TenderDatabase:

    def __init__(self, db_path: str = TENDER_DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init()
        log.info(f"Tender database ready: {db_path}")

    def _init(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(CREATE_TABLE)
            conn.execute(CREATE_RUNS)
            conn.commit()

    def upsert(self, rec: dict) -> bool:
        """Insert or update. Returns True if NEW record."""
        now = datetime.now().isoformat()
        tid = rec.get("tender_id", "")
        if not tid:
            log.warning("Skipping record with no tender_id")
            return False

        with sqlite3.connect(self.db_path) as conn:
            existing = conn.execute(
                "SELECT tender_id FROM tenders WHERE tender_id = ?", (tid,)
            ).fetchone()

            doc_urls = rec.get("document_urls", [])
            if isinstance(doc_urls, list):
                doc_urls = json.dumps(doc_urls)

            all_bidders = rec.get("all_bidders", "[]")

            if existing:
                conn.execute("""
                    UPDATE tenders SET
                        status=?, tender_value=?, contract_value=?,
                        winner_name=?, winner_bid=?, all_bidders=?,
                        last_seen=?, is_new=0
                    WHERE tender_id=?
                """, (
                    rec.get("status", ""),
                    rec.get("tender_value", ""),
                    rec.get("contract_value", ""),
                    rec.get("winner_name", ""),
                    rec.get("winner_bid", ""),
                    all_bidders,
                    now, tid
                ))
                conn.commit()
                return False
            else:
                cols = [f for f in rec.keys() if f not in ("document_urls", "all_bidders")]
                vals = [rec[c] for c in cols]
                cols += ["document_urls", "all_bidders", "first_seen", "last_seen", "is_new"]
                vals += [doc_urls, all_bidders, now, now, 1]

                placeholders = ",".join(["?"] * len(vals))
                conn.execute(
                    f"INSERT OR IGNORE INTO tenders ({','.join(cols)}) VALUES ({placeholders})",
                    vals
                )
                conn.commit()
                log.info(f"  NEW TENDER saved: {tid} — {rec.get('authority','')[:40]}")
                return True

    def upsert_many(self, records: list[dict]) -> tuple[int, int]:
        """Upsert a batch. Returns (total, new_count)."""
        new_count = 0
        for r in records:
            if self.upsert(r):
                new_count += 1
        return len(records), new_count

    def log_run(self, total: int, new_count: int, source: str = ""):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO tender_runs (run_at, total, new_count, source) VALUES (?,?,?,?)",
                (datetime.now().isoformat(), total, new_count, source)
            )
            conn.commit()

    def get_all(self, status: str | None = None) -> list[dict]:
        query = "SELECT * FROM tenders"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY first_seen DESC"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def export_json(self, path: str | None = None) -> str:
        if not path:
            path = _DEFAULT_JSON_PATH
        records = self.get_all()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        log.info(f"Exported {len(records)} tenders → {path}")
        return path

    def stats(self) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            total   = conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
            open_c  = conn.execute("SELECT COUNT(*) FROM tenders WHERE status='OPEN'").fetchone()[0]
            aoc_c   = conn.execute("SELECT COUNT(*) FROM tenders WHERE status='AOC'").fetchone()[0]
            new_c   = conn.execute("SELECT COUNT(*) FROM tenders WHERE is_new=1").fetchone()[0]
            runs    = conn.execute("SELECT COUNT(*) FROM tender_runs").fetchone()[0]
        return {
            "total": total, "open": open_c,
            "aoc": aoc_c, "new": new_c, "runs": runs
        }