# =========================================================================
# tasks/tier3_atc_rag.py
# Tier 3 Worker: Gemini ATC Compliance & Semantic Vector Indexing
# Route: atc_rag_queue
# =========================================================================
import json
import os
import redis
from pathlib import Path
from typing import Any, Dict, List, Optional

from tasks.celery_app import app
from config.settings import (
    DOWNLOAD_DIR,
    ENABLE_ATC_ANALYSIS,
    GEMINI_API_KEY,
    OPENAI_API_KEY,
    REDIS_URL,
)
from core.atc_analyzer import analyze_bid_atc
from core.embedder import generate_bid_embeddings
from storage.postgres_db import PostgresBidDatabase, get_db_cursor
from utils.logger import get_logger

log = get_logger("tier3_atc_rag")


def _get_redis_client():
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


@app.task(name="tasks.tier3_atc_rag.process_atc_and_embed", bind=True, max_retries=2)
def process_atc_and_embed(
    self,
    safe_bid_no: str,
    pdf_text: str,
    bid_hyperlinks: List[Dict[str, Any]],
    parsed_pdf_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Tier 3 Worker Task:
    1. Runs Gemini 2.5 Flash / 3.1 Flash Lite 8-domain ATC compliance engine.
    2. Inserts checklist items, physical offline submissions, and AI telemetry into PostgreSQL.
    3. Updates local JSON artifact with complete compliance intelligence.
    4. Marks tender completion status in Redis.
    """
    log.info(f"[Tier 3] Starting ATC analysis & indexing for: {safe_bid_no}")
    candidate_dir = os.path.join(DOWNLOAD_DIR, safe_bid_no)
    bid_dir = candidate_dir if os.path.exists(candidate_dir) else None

    atc_result: Dict[str, Any] = {}
    if ENABLE_ATC_ANALYSIS and (GEMINI_API_KEY or OPENAI_API_KEY):
        try:
            atc_result = analyze_bid_atc(
                bid_no=safe_bid_no,
                markdown_text=pdf_text,
                hyperlinks=bid_hyperlinks,
                save_dir=bid_dir,
                parsed_pdf_data=parsed_pdf_data,
            )
            log.info(f"[Tier 3] ATC Analysis completed for {safe_bid_no}: status={atc_result.get('status')}")
        except Exception as e:
            log.error(f"[Tier 3] ATC analysis failed for {safe_bid_no}: {e}", exc_info=True)
            atc_result = {"status": "error", "error": str(e), "has_atc": False}
    else:
        log.info(f"[Tier 3] ATC analysis skipped (disabled or no API key) for {safe_bid_no}")
        atc_result = {"status": "skipped_disabled", "has_atc": False}

    # 1. Update PostgreSQL with ATC results
    full_doc = None
    try:
        db = PostgresBidDatabase()
        # Read existing bid record if available to preserve full document
        final_json_path = os.path.join(bid_dir, f"{safe_bid_no}.json")
        if os.path.exists(final_json_path):
            with open(final_json_path, "r", encoding="utf-8") as fp:
                full_doc = json.load(fp)
        elif not full_doc:
            # Check MinIO S3 for metadata.json if not on local disk
            s3_meta_key = f"bids/{safe_bid_no}/metadata.json"
            try:
                from utils.s3_storage import object_exists, download_bytes
                if object_exists(s3_meta_key):
                    raw_meta_bytes = download_bytes(s3_meta_key)
                    full_doc = json.loads(raw_meta_bytes.decode("utf-8"))
                    log.info(f"[Tier 3] Restored metadata.json from MinIO: {s3_meta_key}")
            except Exception as meta_err:
                log.warning(f"[Tier 3] Could not fetch metadata from MinIO: {meta_err}")

        # Verify parent record exists in PostgreSQL 'bids' table to satisfy Foreign Key constraints
        bid_exists_in_db = False
        with get_db_cursor(commit=False) as cur:
            cur.execute("SELECT 1 FROM bids WHERE id = %s;", (safe_bid_no,))
            bid_exists_in_db = bool(cur.fetchone())

        if not bid_exists_in_db:
            log.warning(f"[Tier 3] Parent record for {safe_bid_no} not present in 'bids' table! Performing self-healing upsert...")
            parent_to_upsert = full_doc if full_doc else {
                "_id": safe_bid_no,
                "bid": {"bid_no": safe_bid_no.replace("_", "/")},
                "card": {"bid_no": safe_bid_no.replace("_", "/")},
                "pdf": parsed_pdf_data or {},
                "hyperlinks": bid_hyperlinks or [],
                "normalized": {},
                "atc_analysis": atc_result,
                "full_pdf_text": pdf_text,
            }
            db.upsert_bid(parent_to_upsert)

        if full_doc:
            full_doc["atc_analysis"] = atc_result
            if os.path.exists(final_json_path):
                with open(final_json_path, "w", encoding="utf-8") as fp:
                    json.dump(full_doc, fp, ensure_ascii=False, indent=4, default=str)
            db.upsert_bid(full_doc)
        else:
            with get_db_cursor(commit=True) as cur:
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
                        "bid_id": safe_bid_no,
                        "status": (atc_result.get("status") or "success")[:32],
                        "has_atc": bool(atc_result.get("has_atc", False)),
                        "elapsed_seconds": atc_result.get("elapsed_seconds"),
                        "cost_usd": atc_result.get("cost_usd"),
                        "cost_inr": atc_result.get("cost_inr"),
                        "input_tokens": atc_result.get("tokens", {}).get("input"),
                        "output_tokens": atc_result.get("tokens", {}).get("output"),
                        "error_message": atc_result.get("error"),
                    },
                )
        log.info(f"[Tier 3] ATC results written to PostgreSQL for {safe_bid_no}")
    except Exception as db_err:
        log.error(f"[Tier 3] Failed to update PostgreSQL with ATC results for {safe_bid_no}: {db_err}", exc_info=True)

    # 2. Domain Vector Embedding Generation & pgvector Indexing
    total_chunks_indexed = 0
    try:
        log.info(f"[Tier 3] Generating vector embeddings for {safe_bid_no}...")
        bid_dict = full_doc if full_doc else {
            "_id": safe_bid_no,
            "bid": {"bid_no": safe_bid_no.replace("_", "/")},
            "pdf": parsed_pdf_data,
            "hyperlinks": bid_hyperlinks,
            "full_pdf_text": pdf_text,
            "atc_analysis": atc_result,
        }
        chunks_with_embeddings = generate_bid_embeddings(
            bid_data=bid_dict,
            atc_result=atc_result,
            pdf_text=pdf_text,
        )
        if chunks_with_embeddings:
            db_inst = PostgresBidDatabase()
            total_chunks_indexed = db_inst.insert_chunks(safe_bid_no, chunks_with_embeddings)
            log.info(f"[Tier 3] Successfully indexed {total_chunks_indexed} vector chunks into gem_bid_chunks for {safe_bid_no}")
        else:
            log.warning(f"[Tier 3] No vector chunks produced for {safe_bid_no}")
    except Exception as emb_err:
        log.error(f"[Tier 3] Vector embedding generation failed for {safe_bid_no}: {emb_err}", exc_info=True)

    # 3. Upload ATC results to MinIO S3
    try:
        from utils.s3_storage import upload_bytes as s3_upload_bytes
        s3_upload_bytes(f"bids/{safe_bid_no}/atc_compliance.json", json.dumps(atc_result, default=str).encode("utf-8"), content_type="application/json")
        log.info(f"[Tier 3] Streamed atc_compliance.json to MinIO for {safe_bid_no}")
    except Exception as s3_err:
        log.warning(f"[Tier 3] MinIO upload failed for {safe_bid_no}: {s3_err}")

    # 4. Mark Redis key as completed
    try:
        r = _get_redis_client()
        r.set(f"gem:seen:{safe_bid_no}", "completed", ex=86400 * 30)
    except Exception as redis_err:
        log.warning(f"[Tier 3] Redis status update failed: {redis_err}")

    log.info(f"[Tier 3] Tender {safe_bid_no} 100% processed and indexed.")
    return {
        "status": "completed",
        "bid_no": safe_bid_no,
        "has_atc": atc_result.get("has_atc", False),
        "chunks_indexed": total_chunks_indexed,
    }
