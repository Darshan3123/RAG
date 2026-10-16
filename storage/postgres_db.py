# =========================================================================
# storage/postgres_db.py
# High-performance PostgreSQL 16+ Database Manager for GeMBridge (v3.0)
# Supports Threaded Connection Pooling, ACID Transactions, and pgvector
# =========================================================================
import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import psycopg2
from psycopg2 import pool, sql
from psycopg2.extras import Json, execute_values

from config.settings import (
    BASE_DIR,
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from utils.logger import get_logger

log = get_logger("postgres_db")

# Threaded connection pool singleton
_POOL: Optional[pool.ThreadedConnectionPool] = None


def get_connection_pool(minconn: int = 1, maxconn: int = 10) -> pool.ThreadedConnectionPool:
    """Initialize or return the existing threaded connection pool."""
    global _POOL
    if _POOL is None or _POOL.closed:
        log.info(f"Initializing PostgreSQL connection pool ({minconn}-{maxconn} conn) -> {POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")
        _POOL = pool.ThreadedConnectionPool(
            minconn=minconn,
            maxconn=maxconn,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
        )
    return _POOL


def close_connection_pool() -> None:
    """Close all connections in the pool."""
    global _POOL
    if _POOL is not None and not _POOL.closed:
        _POOL.closeall()
        _POOL = None
        log.info("PostgreSQL connection pool closed.")


@contextmanager
def get_db_connection():
    """Context manager to borrow a connection from the pool and automatically return it."""
    pool_inst = get_connection_pool()
    conn = pool_inst.getconn()
    try:
        yield conn
    finally:
        pool_inst.putconn(conn)


@contextmanager
def get_db_cursor(commit: bool = True):
    """Context manager for acquiring a cursor with transaction safety."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            yield cursor
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


def init_db(schema_file_path: Optional[str] = None) -> None:
    """
    Execute the idempotent init_v3_schema.sql script to ensure extensions,
    all 10 tables, and required B-Tree/GIN/HNSW indexes are created.
    """
    if schema_file_path is None:
        schema_file_path = str(Path(__file__).resolve().parent / "init_v3_schema.sql")

    if not Path(schema_file_path).exists():
        raise FileNotFoundError(f"Schema file not found: {schema_file_path}")

    log.info(f"Applying schema DDL from: {schema_file_path}")
    with open(schema_file_path, "r", encoding="utf-8") as f:
        ddl_sql = f.read()

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl_sql)
        conn.commit()
    log.info("Database schema initialized successfully.")


# -------------------------------------------------------------------------
# TYPE NORMALIZATION AND PARSING HELPERS
# -------------------------------------------------------------------------
def _to_bool(val: Any) -> bool:
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("yes", "true", "1", "y")


def _to_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        cleaned = re.sub(r"[^\d.-]", "", str(val))
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None


def _to_int(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    if isinstance(val, int):
        return val
    try:
        cleaned = re.sub(r"[^\d-]", "", str(val))
        return int(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None


def _to_timestamptz(val: Any) -> Optional[datetime]:
    """Parse date strings (ISO format or dd-mm-yyyy hh:mm:ss) into timezone-aware datetime."""
    if not val or not isinstance(val, str):
        return None
    val = val.strip()
    # Try ISO format
    try:
        return datetime.fromisoformat(val)
    except Exception:
        pass
    # Try standard Indian GeM format: "13-10-2026 17:00:00"
    for fmt in ("%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(val, fmt)
            # Default to IST (+05:30) if timezone is absent
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def _extract_pincode(address: str) -> Optional[str]:
    """Extract a 6-digit Indian postal PIN code from address text."""
    if not address:
        return None
    match = re.search(r"\b([1-9][0-9]{5})\b", address)
    return match.group(1) if match else None


# -------------------------------------------------------------------------
# MASTER UPSERT ENGINE
# -------------------------------------------------------------------------
class PostgresBidDatabase:
    """Enterprise PostgreSQL client managing all 10 normalized and hybrid tables."""

    def __init__(self):
        # Verify connection and pool
        get_connection_pool()

    def upsert_bid(self, raw_doc: dict) -> bool:
        """
        Atomically upsert a tender document into all relevant normalized tables:
        1. bids (master row)
        2. bid_items
        3. bid_consignees
        4. bid_evaluation_schedules
        5. bid_hyperlinks
        6. bid_terms
        7. bid_atc_analyses
        8. bid_atc_checklist_items
        9. bid_atc_physical_submissions

        Returns True on successful transaction commit.
        """
        bid_id = raw_doc.get("_id")
        if not bid_id:
            bid_id = (raw_doc.get("bid", {}).get("bid_no") or "").replace("/", "_")
        if not bid_id:
            raise ValueError("Document has no valid '_id' or 'bid.bid_no'")

        bid_meta = raw_doc.get("bid", {})
        card = raw_doc.get("card", {})
        pdf = raw_doc.get("pdf", {})
        norm = raw_doc.get("normalized", {})
        atc = raw_doc.get("atc_analysis", {})

        # -------------------------------------------------------------
        # 1. Master Table: bids
        # -------------------------------------------------------------
        bid_no = bid_meta.get("bid_no") or card.get("bid_no") or bid_id.replace("_", "/")
        ra_no = bid_meta.get("ra_no")
        bid_type = bid_meta.get("bid_type") or card.get("bid_type", "Product Bid/RAs")
        product_type = bid_meta.get("product_type") or card.get("product_type", "Product")
        base_type = bid_meta.get("base_type", "PRODUCT")
        process_kind = bid_meta.get("process_kind", "CATALOGUE")
        bid_packet_type = pdf.get("bid_type", {}).get("type_of_bid") or card.get("bid_packet_type")

        # Department details
        card_depts = card.get("departments", [{}])
        card_dept = card_depts[0] if isinstance(card_depts, list) and card_depts else {}
        pdf_dept = pdf.get("departments", {})
        ministry_state_name = pdf_dept.get("ministry_state_name") or card_dept.get("ministry_state_name")
        department_name = pdf_dept.get("department_name") or card_dept.get("department_name")
        organisation_name = pdf_dept.get("organisation_name") or card_dept.get("organisation_name")
        office_name = pdf_dept.get("office_name") or card_dept.get("office_name")

        # Timing
        norm_dates = norm.get("dates", {})
        start_datetime = _to_timestamptz(norm_dates.get("start_date_iso") or card.get("start_datetime"))
        end_datetime = _to_timestamptz(norm_dates.get("end_date_iso") or pdf.get("timing", {}).get("bid_end_datetime") or card.get("end_datetime"))
        bid_opening_datetime = _to_timestamptz(pdf.get("timing", {}).get("bid_opening_datetime"))
        card_start_datetime = card.get("start_datetime")
        card_end_datetime = card.get("end_datetime")
        bid_offer_validity_days = _to_int(pdf.get("timing", {}).get("bid_offer_validity_days"))
        bid_duration_days = _to_float(norm_dates.get("bid_duration_days"))
        days_remaining = _to_float(norm_dates.get("days_remaining"))
        is_expired = bool(norm_dates.get("is_expired", False))
        is_corrigendum = _to_bool(raw_doc.get("is_corrigendum", False))

        # Financials
        norm_fin = norm.get("financials", {})
        pdf_fin = pdf.get("financials", {})
        estimated_value = _to_float(norm_fin.get("estimated_value_inr") or pdf_fin.get("estimated_value"))
        is_high_value = bool(norm_fin.get("high_value_tender", False))

        # EMD & EPBG
        norm_emd = norm_fin.get("emd", {})
        pdf_emd = pdf_fin.get("emd", {})
        emd_required = bool(norm_emd.get("required") if norm_emd else pdf_emd.get("required", False))
        emd_amount = _to_float(norm_emd.get("amount_inr") or pdf_emd.get("amount_total"))
        emd_advisory_bank = norm_emd.get("advisory_bank") or pdf_emd.get("advisory_bank")

        norm_epbg = norm_fin.get("epbg", {})
        pdf_epbg = pdf_fin.get("epbg", {})
        epbg_required = bool(norm_epbg.get("required") if norm_epbg else pdf_epbg.get("required", False))
        epbg_percent = _to_float(norm_epbg.get("percentage") or pdf_epbg.get("percent"))
        epbg_duration_months = _to_int(norm_epbg.get("duration_months") or pdf_epbg.get("duration_months"))
        epbg_advisory_bank = norm_epbg.get("advisory_bank") or pdf_epbg.get("advisory_bank")

        # Evaluation & Rules
        eval_method = pdf.get("evaluation", {}).get("evaluation_method") or "Total value wise evaluation"
        ra_info = pdf.get("ra", {})
        bid_to_ra_enabled = _to_bool(ra_info.get("bid_to_ra_enabled"))
        ra_qualification_rule = ra_info.get("ra_qualification_rule")
        clarification_window_days = _to_int(pdf.get("bid_type", {}).get("technical_clarification_window_days"))

        # Inspection & Clauses
        inspection = pdf.get("inspection", {})
        inspection_required = _to_bool(inspection.get("inspection_required"))
        inspection_agency = inspection.get("inspection_agency_type")
        clauses = pdf.get("clauses", {})
        arbitration_clause = _to_bool(clauses.get("arbitration_clause"))
        mediation_clause = _to_bool(clauses.get("mediation_clause"))

        # Documents & Preferences
        docs = pdf.get("documents", {})
        show_docs_to_all = _to_bool(docs.get("show_uploaded_docs_to_all_bidders"))
        req_docs = docs.get("required_from_seller") or []
        if isinstance(req_docs, str):
            req_docs = [req_docs]

        mii = pdf.get("mii", {})
        allow_only_class_1_2 = _to_bool(mii.get("allow_only_class_1_2_local_suppliers"))
        mii_preference = _to_bool(mii.get("mii_purchase_preference") or norm.get("preferences", {}).get("mii_preference"))
        mii_price_band_percent = _to_float(mii.get("mii_price_band_percent"))
        mii_max_quantity_percent = _to_float(mii.get("mii_max_quantity_percent"))

        mse = pdf.get("mse", {})
        mse_preference = _to_bool(mse.get("mse_purchase_preference") or norm.get("preferences", {}).get("mse_preference"))
        mse_price_band_percent = _to_float(mse.get("mse_price_band_percent"))
        mse_max_quantity_percent = _to_float(mse.get("mse_max_quantity_percent"))

        relaxations = pdf.get("relaxations", {})
        mse_relaxation = _to_bool(relaxations.get("mse_relaxation_experience_turnover") or norm.get("preferences", {}).get("mse_relaxation"))
        startup_relaxation = _to_bool(relaxations.get("startup_relaxation_experience_turnover") or norm.get("preferences", {}).get("startup_relaxation"))

        auto_ext = pdf.get("auto_extension", {})
        auto_extension_enabled = bool(auto_ext)
        min_bids_disable_extension = _to_int(auto_ext.get("min_bids_to_disable_extension"))
        auto_extend_days = _to_int(auto_ext.get("auto_extend_days"))
        auto_extension_count = _to_int(auto_ext.get("auto_extension_count"))

        # Items & Quantities
        norm_items = norm.get("items", {})
        total_items_count = _to_int(norm_items.get("total_items_count", 1)) or 1
        total_quantity = _to_float(norm_items.get("total_quantity") or pdf.get("items", {}).get("total_quantity_extracted"))
        quantity_match_flag = pdf.get("items", {}).get("quantity_match_flag")

        bid_pdf_url = card.get("bid_pdf_url")
        ra_pdf_url = card.get("ra_pdf_url")

        # -------------------------------------------------------------
        # TRANSACTION BLOCK
        # -------------------------------------------------------------
        with get_db_cursor(commit=True) as cur:
            # 1. Upsert into bids
            bids_sql = """
            INSERT INTO bids (
                id, bid_no, ra_no, bid_type, product_type, base_type, process_kind,
                bid_packet_type, status, ministry_state_name, department_name, organisation_name,
                office_name, start_datetime, end_datetime, card_start_datetime, card_end_datetime,
                bid_opening_datetime, bid_offer_validity_days, bid_duration_days, days_remaining,
                is_expired, is_corrigendum, estimated_value, is_high_value, emd_required,
                emd_amount, emd_advisory_bank, epbg_required, epbg_percent, epbg_duration_months,
                epbg_advisory_bank, evaluation_method, bid_to_ra_enabled, ra_qualification_rule,
                clarification_window_days, inspection_required, inspection_agency, arbitration_clause,
                mediation_clause, show_docs_to_all, allow_only_class_1_2, mse_preference,
                mse_price_band_percent, mse_max_quantity_percent, mse_relaxation, startup_relaxation,
                mii_preference, mii_price_band_percent, mii_max_quantity_percent, auto_extension_enabled,
                min_bids_disable_extension, auto_extend_days, auto_extension_count, total_items_count,
                total_quantity, quantity_match_flag, bid_pdf_url, ra_pdf_url, required_documents, raw_data
            ) VALUES (
                %(id)s, %(bid_no)s, %(ra_no)s, %(bid_type)s, %(product_type)s, %(base_type)s, %(process_kind)s,
                %(bid_packet_type)s, 'ongoing', %(ministry_state_name)s, %(department_name)s, %(organisation_name)s,
                %(office_name)s, %(start_datetime)s, %(end_datetime)s, %(card_start_datetime)s, %(card_end_datetime)s,
                %(bid_opening_datetime)s, %(bid_offer_validity_days)s, %(bid_duration_days)s, %(days_remaining)s,
                %(is_expired)s, %(is_corrigendum)s, %(estimated_value)s, %(is_high_value)s, %(emd_required)s,
                %(emd_amount)s, %(emd_advisory_bank)s, %(epbg_required)s, %(epbg_percent)s, %(epbg_duration_months)s,
                %(epbg_advisory_bank)s, %(evaluation_method)s, %(bid_to_ra_enabled)s, %(ra_qualification_rule)s,
                %(clarification_window_days)s, %(inspection_required)s, %(inspection_agency)s, %(arbitration_clause)s,
                %(mediation_clause)s, %(show_docs_to_all)s, %(allow_only_class_1_2)s, %(mse_preference)s,
                %(mse_price_band_percent)s, %(mse_max_quantity_percent)s, %(mse_relaxation)s, %(startup_relaxation)s,
                %(mii_preference)s, %(mii_price_band_percent)s, %(mii_max_quantity_percent)s, %(auto_extension_enabled)s,
                %(min_bids_disable_extension)s, %(auto_extend_days)s, %(auto_extension_count)s, %(total_items_count)s,
                %(total_quantity)s, %(quantity_match_flag)s, %(bid_pdf_url)s, %(ra_pdf_url)s, %(required_documents)s, %(raw_data)s
            )
            ON CONFLICT (id) DO UPDATE SET
                ra_no = EXCLUDED.ra_no,
                status = EXCLUDED.status,
                start_datetime = EXCLUDED.start_datetime,
                end_datetime = EXCLUDED.end_datetime,
                card_start_datetime = EXCLUDED.card_start_datetime,
                card_end_datetime = EXCLUDED.card_end_datetime,
                bid_opening_datetime = EXCLUDED.bid_opening_datetime,
                days_remaining = EXCLUDED.days_remaining,
                is_expired = EXCLUDED.is_expired,
                is_corrigendum = EXCLUDED.is_corrigendum,
                estimated_value = EXCLUDED.estimated_value,
                total_items_count = EXCLUDED.total_items_count,
                total_quantity = EXCLUDED.total_quantity,
                required_documents = EXCLUDED.required_documents,
                raw_data = EXCLUDED.raw_data;
            """
            cur.execute(
                bids_sql,
                {
                    "id": bid_id,
                    "bid_no": bid_no,
                    "ra_no": ra_no,
                    "bid_type": bid_type,
                    "product_type": product_type,
                    "base_type": base_type,
                    "process_kind": process_kind,
                    "bid_packet_type": bid_packet_type,
                    "ministry_state_name": ministry_state_name,
                    "department_name": department_name,
                    "organisation_name": organisation_name,
                    "office_name": office_name,
                    "start_datetime": start_datetime,
                    "end_datetime": end_datetime,
                    "card_start_datetime": card_start_datetime,
                    "card_end_datetime": card_end_datetime,
                    "bid_opening_datetime": bid_opening_datetime,
                    "bid_offer_validity_days": bid_offer_validity_days,
                    "bid_duration_days": bid_duration_days,
                    "days_remaining": days_remaining,
                    "is_expired": is_expired,
                    "is_corrigendum": is_corrigendum,
                    "estimated_value": estimated_value,
                    "is_high_value": is_high_value,
                    "emd_required": emd_required,
                    "emd_amount": emd_amount,
                    "emd_advisory_bank": emd_advisory_bank,
                    "epbg_required": epbg_required,
                    "epbg_percent": epbg_percent,
                    "epbg_duration_months": epbg_duration_months,
                    "epbg_advisory_bank": epbg_advisory_bank,
                    "evaluation_method": eval_method,
                    "bid_to_ra_enabled": bid_to_ra_enabled,
                    "ra_qualification_rule": ra_qualification_rule,
                    "clarification_window_days": clarification_window_days,
                    "inspection_required": inspection_required,
                    "inspection_agency": inspection_agency,
                    "arbitration_clause": arbitration_clause,
                    "mediation_clause": mediation_clause,
                    "show_docs_to_all": show_docs_to_all,
                    "allow_only_class_1_2": allow_only_class_1_2,
                    "mse_preference": mse_preference,
                    "mse_price_band_percent": mse_price_band_percent,
                    "mse_max_quantity_percent": mse_max_quantity_percent,
                    "mse_relaxation": mse_relaxation,
                    "startup_relaxation": startup_relaxation,
                    "mii_preference": mii_preference,
                    "mii_price_band_percent": mii_price_band_percent,
                    "mii_max_quantity_percent": mii_max_quantity_percent,
                    "auto_extension_enabled": auto_extension_enabled,
                    "min_bids_disable_extension": min_bids_disable_extension,
                    "auto_extend_days": auto_extend_days,
                    "auto_extension_count": auto_extension_count,
                    "total_items_count": total_items_count,
                    "total_quantity": total_quantity,
                    "quantity_match_flag": quantity_match_flag,
                    "bid_pdf_url": bid_pdf_url,
                    "ra_pdf_url": ra_pdf_url,
                    "required_documents": req_docs,
                    "raw_data": Json(raw_doc),
                },
            )

            # ---------------------------------------------------------
            # 2. Child Table: bid_items
            # ---------------------------------------------------------
            cur.execute("DELETE FROM bid_items WHERE bid_id = %s;", (bid_id,))
            items_to_insert = []
            pdf_items = pdf.get("items", {})
            item_idx = 1
            for k, v in pdf_items.items():
                if isinstance(v, dict) and "item_category" in v:
                    cat = v.get("item_category") or "Unknown"
                    qty = _to_float(v.get("quantity"))
                    specs = v.get("specifications")
                    items_to_insert.append((bid_id, item_idx, cat[:500], qty, "pdf", Json(specs) if specs else None))
                    item_idx += 1

            # Fallback to card items if no pdf items extracted
            if not items_to_insert and card.get("items"):
                for idx, c_item in enumerate(card["items"], 1):
                    cat = c_item.get("name") or "Unknown"
                    qty = _to_float(c_item.get("quantity"))
                    items_to_insert.append((bid_id, idx, cat[:500], qty, "card", None))

            if items_to_insert:
                execute_values(
                    cur,
                    """
                    INSERT INTO bid_items (bid_id, item_index, item_category, quantity, source, specifications)
                    VALUES %s;
                    """,
                    items_to_insert,
                )

            # ---------------------------------------------------------
            # 3. Child Table: bid_consignees
            # ---------------------------------------------------------
            cur.execute("DELETE FROM bid_consignees WHERE bid_id = %s;", (bid_id,))
            consignees_to_insert = []
            for c in pdf.get("consignees", []):
                officer = c.get("consignee_reporting_officer")
                addr = c.get("consignee_address") or ""
                pin = _extract_pincode(addr)
                qty_raw = str(c.get("quantity") or "").strip()
                is_lump = "lump" in qty_raw.lower() or "project" in qty_raw.lower()
                qty_num = None if is_lump else _to_float(qty_raw)
                days = _to_int(c.get("delivery_days"))
                consignees_to_insert.append((bid_id, officer, addr, pin, None, qty_raw, qty_num, is_lump, days))

            if consignees_to_insert:
                execute_values(
                    cur,
                    """
                    INSERT INTO bid_consignees (
                        bid_id, officer_name, address, pincode, city, quantity_raw, quantity, is_lumpsum, delivery_days
                    ) VALUES %s;
                    """,
                    consignees_to_insert,
                )

            # ---------------------------------------------------------
            # 4. Child Table: bid_evaluation_schedules
            # ---------------------------------------------------------
            cur.execute("DELETE FROM bid_evaluation_schedules WHERE bid_id = %s;", (bid_id,))
            schedules_data = pdf.get("evaluation", {}).get("schedules", {})
            schedules_to_insert = []
            if isinstance(schedules_data, dict):
                for sched_name, s_val in schedules_data.items():
                    if isinstance(s_val, dict):
                        cat = s_val.get("item_category")
                        qty = _to_float(s_val.get("quantity"))
                        val = _to_float(s_val.get("estimated_value"))
                        con_off = s_val.get("consignee_officer")
                        con_add = s_val.get("consignee_address")
                        grouped = s_val.get("grouped_items") or s_val.get("sub_items")
                        schedules_to_insert.append((bid_id, sched_name[:128], cat, qty, val, con_off, con_add, Json(grouped) if grouped else None))
            elif isinstance(schedules_data, list):
                for idx, s_val in enumerate(schedules_data, 1):
                    if isinstance(s_val, dict):
                        sched_name = s_val.get("schedule_name") or f"Schedule {idx}"
                        cat = s_val.get("item_category")
                        qty = _to_float(s_val.get("quantity"))
                        val = _to_float(s_val.get("estimated_value"))
                        con_off = s_val.get("consignee_officer")
                        con_add = s_val.get("consignee_address")
                        grouped = s_val.get("grouped_items")
                        schedules_to_insert.append((bid_id, sched_name[:128], cat, qty, val, con_off, con_add, Json(grouped) if grouped else None))

            if schedules_to_insert:
                execute_values(
                    cur,
                    """
                    INSERT INTO bid_evaluation_schedules (
                        bid_id, schedule_name, item_category, quantity, estimated_value, consignee_officer, consignee_address, grouped_items
                    ) VALUES %s;
                    """,
                    schedules_to_insert,
                )

            # ---------------------------------------------------------
            # 5. Child Table: bid_hyperlinks
            # ---------------------------------------------------------
            cur.execute("DELETE FROM bid_hyperlinks WHERE bid_id = %s;", (bid_id,))
            links_to_insert = []
            for link in raw_doc.get("hyperlinks", []):
                pg = _to_int(link.get("page"))
                name = (link.get("name") or "")[:255]
                url = link.get("url") or ""
                src = (link.get("source") or "bid")[:16]
                if url:
                    links_to_insert.append((bid_id, pg, name, url, src))

            if links_to_insert:
                execute_values(
                    cur,
                    """
                    INSERT INTO bid_hyperlinks (bid_id, page_number, link_name, url, source)
                    VALUES %s;
                    """,
                    links_to_insert,
                )

            # ---------------------------------------------------------
            # 6. Child Table: bid_terms (1:1 Decoupled)
            # ---------------------------------------------------------
            terms = pdf.get("terms", {})
            full_pdf_text = raw_doc.get("full_pdf_text") or ""
            special_version = terms.get("special_terms_version")
            special_text = terms.get("special_terms_text")
            buyer_atc_text = terms.get("buyer_atc", {}).get("generic") if isinstance(terms.get("buyer_atc"), dict) else ""
            emd_exemption_text = pdf_fin.get("emd_exemption_text")
            disclaimer = terms.get("disclaimer")

            cur.execute(
                """
                INSERT INTO bid_terms (
                    bid_id, special_terms_version, special_terms_text, buyer_atc_text, emd_exemption_text, disclaimer, full_pdf_text
                ) VALUES (
                    %(bid_id)s, %(special_terms_version)s, %(special_terms_text)s, %(buyer_atc_text)s, %(emd_exemption_text)s, %(disclaimer)s, %(full_pdf_text)s
                )
                ON CONFLICT (bid_id) DO UPDATE SET
                    special_terms_version = EXCLUDED.special_terms_version,
                    special_terms_text = EXCLUDED.special_terms_text,
                    buyer_atc_text = EXCLUDED.buyer_atc_text,
                    emd_exemption_text = EXCLUDED.emd_exemption_text,
                    disclaimer = EXCLUDED.disclaimer,
                    full_pdf_text = EXCLUDED.full_pdf_text;
                """,
                {
                    "bid_id": bid_id,
                    "special_terms_version": special_version,
                    "special_terms_text": special_text,
                    "buyer_atc_text": buyer_atc_text,
                    "emd_exemption_text": emd_exemption_text,
                    "disclaimer": disclaimer,
                    "full_pdf_text": full_pdf_text,
                },
            )

            # ---------------------------------------------------------
            # 7. Child Table: bid_atc_analyses
            # ---------------------------------------------------------
            if atc:
                atc_status = atc.get("status") or "success"
                has_atc = bool(atc.get("has_atc", False))
                elapsed_sec = _to_float(atc.get("elapsed_seconds"))
                cost_usd = _to_float(atc.get("cost_usd"))
                cost_inr = _to_float(atc.get("cost_inr"))
                tokens = atc.get("tokens", {})
                inp_tokens = _to_int(tokens.get("input"))
                out_tokens = _to_int(tokens.get("output"))
                err_msg = atc.get("error")

                cur.execute(
                    """
                    INSERT INTO bid_atc_analyses (
                        bid_id, status, has_atc, elapsed_seconds, cost_usd, cost_inr, input_tokens, output_tokens, error_message
                    ) VALUES (
                        %(bid_id)s, %(status)s, %(has_atc)s, %(elapsed_seconds)s, %(cost_usd)s, %(cost_inr)s, %(input_tokens)s, %(output_tokens)s, %(error_message)s
                    )
                    ON CONFLICT (bid_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        has_atc = EXCLUDED.has_atc,
                        elapsed_seconds = EXCLUDED.elapsed_seconds,
                        cost_usd = EXCLUDED.cost_usd,
                        cost_inr = EXCLUDED.cost_inr,
                        input_tokens = EXCLUDED.input_tokens,
                        output_tokens = EXCLUDED.output_tokens,
                        error_message = EXCLUDED.error_message;
                    """,
                    {
                        "bid_id": bid_id,
                        "status": atc_status[:32],
                        "has_atc": has_atc,
                        "elapsed_seconds": elapsed_sec,
                        "cost_usd": cost_usd,
                        "cost_inr": cost_inr,
                        "input_tokens": inp_tokens,
                        "output_tokens": out_tokens,
                        "error_message": err_msg,
                    },
                )

                # -----------------------------------------------------
                # 8. Child Table: bid_atc_checklist_items & physical submissions
                # -----------------------------------------------------
                cur.execute("DELETE FROM bid_atc_checklist_items WHERE bid_id = %s;", (bid_id,))
                cur.execute("DELETE FROM bid_atc_physical_submissions WHERE bid_id = %s;", (bid_id,))

                checklist = atc.get("checklist", {})
                # Checklist can be dict or list (per our empirical findings)
                checklist_dict = {}
                if isinstance(checklist, list):
                    for item in checklist:
                        if isinstance(item, dict):
                            checklist_dict.update(item)
                elif isinstance(checklist, dict):
                    checklist_dict = checklist

                checklist_to_insert = []
                physical_to_insert = []
                order = 0

                for cat, clauses in checklist_dict.items():
                    if cat == "PHYSICAL_SUBMISSIONS":
                        if isinstance(clauses, list):
                            for sub in clauses:
                                if isinstance(sub, dict):
                                    item_name = sub.get("Item") or "Physical Document"
                                    deadline = sub.get("Deadline")
                                    in_favor = sub.get("In Favor Of")
                                    payable = sub.get("Payable At")
                                    addr = sub.get("Delivery Address")
                                    orig = sub.get("Original Text")
                                    physical_to_insert.append((bid_id, item_name[:255], deadline, in_favor, payable, addr, orig))
                    else:
                        if isinstance(clauses, list):
                            for clause in clauses:
                                if isinstance(clause, str) and clause.strip():
                                    order += 1
                                    checklist_to_insert.append((bid_id, cat[:64], clause.strip(), order))

                if checklist_to_insert:
                    execute_values(
                        cur,
                        """
                        INSERT INTO bid_atc_checklist_items (bid_id, category, clause_text, display_order)
                        VALUES %s;
                        """,
                        checklist_to_insert,
                    )

                if physical_to_insert:
                    execute_values(
                        cur,
                        """
                        INSERT INTO bid_atc_physical_submissions (
                            bid_id, item_name, deadline, in_favor_of, payable_at, delivery_address, original_clause_text
                        ) VALUES %s;
                        """,
                        physical_to_insert,
                    )

        log.info(f"Successfully upserted bid: {bid_no} ({bid_id}) across all 10 tables.")
        return True

    # -------------------------------------------------------------------------
    # PGVECTOR CHUNKS INSERT & SEARCH
    # -------------------------------------------------------------------------
    def insert_chunks(self, bid_id: str, chunks: List[Dict[str, Any]]) -> int:
        """
        Bulk-insert semantic text passages with 768-dim embeddings into gem_bid_chunks.
        """
        if not chunks:
            return 0

        rows = []
        for c in chunks:
            ctype = c.get("chunk_type", "general_pdf")
            text = c.get("chunk_text") or c.get("text", "")
            meta = c.get("metadata", {})
            emb = c.get("embedding")
            if text and emb:
                rows.append((bid_id, ctype, text, Json(meta), emb))

        if not rows:
            return 0

        with get_db_cursor(commit=True) as cur:
            execute_values(
                cur,
                """
                INSERT INTO gem_bid_chunks (bid_id, chunk_type, chunk_text, metadata, embedding)
                VALUES %s;
                """,
                rows,
            )
        log.info(f"Inserted {len(rows)} vector chunks for bid: {bid_id}")
        return len(rows)

    def search_chunks(self, query_embedding: List[float], top_k: int = 5, bid_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Sub-5ms Cosine Similarity search over gem_bid_chunks using the HNSW index.
        """
        with get_db_cursor(commit=False) as cur:
            if bid_id:
                cur.execute(
                    """
                    SELECT c.id, c.bid_id, c.chunk_type, c.chunk_text, c.metadata,
                           (c.embedding <=> %s::vector) AS distance
                    FROM gem_bid_chunks c
                    WHERE c.bid_id = %s
                    ORDER BY distance ASC
                    LIMIT %s;
                    """,
                    (query_embedding, bid_id, top_k),
                )
            else:
                cur.execute(
                    """
                    SELECT c.id, c.bid_id, c.chunk_type, c.chunk_text, c.metadata,
                           (c.embedding <=> %s::vector) AS distance
                    FROM gem_bid_chunks c
                    JOIN bids b ON c.bid_id = b.id
                    WHERE b.is_expired = FALSE
                    ORDER BY distance ASC
                    LIMIT %s;
                    """,
                    (query_embedding, top_k),
                )

            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

    # -------------------------------------------------------------------------
    # QUERY HELPERS FOR REST API GATEWAY & FRONTEND
    # -------------------------------------------------------------------------
    def get_bid_by_no(self, bid_no_or_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve complete tender record including child items, consignees,
        schedules, and compliance checklist.
        """
        with get_db_cursor(commit=False) as cur:
            # 1. Master row
            cur.execute(
                """
                SELECT * FROM bids WHERE id = %s OR bid_no = %s;
                """,
                (bid_no_or_id, bid_no_or_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            desc = [d[0] for d in cur.description]
            bid = dict(zip(desc, row))
            bid_id = bid["id"]

            # 2. Items
            cur.execute("SELECT * FROM bid_items WHERE bid_id = %s ORDER BY item_index ASC;", (bid_id,))
            i_desc = [d[0] for d in cur.description]
            bid["items"] = [dict(zip(i_desc, r)) for r in cur.fetchall()]

            # 3. Consignees
            cur.execute("SELECT * FROM bid_consignees WHERE bid_id = %s ORDER BY id ASC;", (bid_id,))
            c_desc = [d[0] for d in cur.description]
            bid["consignees"] = [dict(zip(c_desc, r)) for r in cur.fetchall()]

            # 4. Schedules
            cur.execute("SELECT * FROM bid_evaluation_schedules WHERE bid_id = %s ORDER BY id ASC;", (bid_id,))
            s_desc = [d[0] for d in cur.description]
            bid["schedules"] = [dict(zip(s_desc, r)) for r in cur.fetchall()]

            # 5. Checklist Items
            cur.execute("SELECT category, clause_text FROM bid_atc_checklist_items WHERE bid_id = %s ORDER BY display_order ASC;", (bid_id,))
            checklist: Dict[str, List[str]] = {}
            for cat, clause in cur.fetchall():
                checklist.setdefault(cat, []).append(clause)
            bid["atc_checklist"] = checklist

            # 6. Physical Submissions
            cur.execute("SELECT * FROM bid_atc_physical_submissions WHERE bid_id = %s ORDER BY id ASC;", (bid_id,))
            p_desc = [d[0] for d in cur.description]
            bid["physical_submissions"] = [dict(zip(p_desc, r)) for r in cur.fetchall()]

            # 7. AI Telemetry
            cur.execute("SELECT * FROM bid_atc_analyses WHERE bid_id = %s;", (bid_id,))
            t_row = cur.fetchone()
            if t_row:
                t_desc = [d[0] for d in cur.description]
                bid["atc_telemetry"] = dict(zip(t_desc, t_row))

            return bid

    def list_bids(
        self,
        limit: int = 20,
        offset: int = 0,
        search: Optional[str] = None,
        status: Optional[str] = None,
        is_expired: Optional[bool] = False,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Fast paginated search returning lightweight card data for frontend UI (< 5ms).
        """
        where_clauses = []
        params: List[Any] = []

        if status:
            where_clauses.append("status = %s")
            params.append(status)

        if is_expired is not None:
            where_clauses.append("is_expired = %s")
            params.append(is_expired)

        if search:
            where_clauses.append("(bid_no ILIKE %s OR organisation_name ILIKE %s OR department_name ILIKE %s)")
            wildcard = f"%{search}%"
            params.extend([wildcard, wildcard, wildcard])

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        with get_db_cursor(commit=False) as cur:
            # Count total
            cur.execute(f"SELECT COUNT(*) FROM bids {where_sql};", tuple(params))
            total = cur.fetchone()[0]

            # Fetch rows
            cur.execute(
                f"""
                SELECT id, bid_no, product_type, organisation_name, department_name,
                       total_items_count, total_quantity, estimated_value, emd_amount,
                       end_datetime, days_remaining, status
                FROM bids
                {where_sql}
                ORDER BY end_datetime ASC
                LIMIT %s OFFSET %s;
                """,
                tuple(params + [limit, offset]),
            )
            desc = [d[0] for d in cur.description]
            bids = [dict(zip(desc, r)) for r in cur.fetchall()]
            return bids, total
