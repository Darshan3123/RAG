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
from pipeline.atc_analyzer import analyze_bid_atc
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
    bid_dir = os.path.join(DOWNLOAD_DIR, safe_bid_no)
    os.makedirs(bid_dir, exist_ok=True)

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
    try:
        db = PostgresBidDatabase()
        # Read existing bid record if available to preserve full document
        final_json_path = os.path.join(bid_dir, f"{safe_bid_no}.json")
        full_doc = None
        if os.path.exists(final_json_path):
            with open(final_json_path, "r", encoding="utf-8") as fp:
                full_doc = json.load(fp)

        if full_doc:
            full_doc["atc_analysis"] = atc_result
            # Write updated JSON to disk
            with open(final_json_path, "w", encoding="utf-8") as fp:
                json.dump(full_doc, fp, ensure_ascii=False, indent=4, default=str)
            # Re-sync to PostgreSQL (updates bid_atc_analyses, checklist, physical submissions)
            db.upsert_bid(full_doc)
        else:
            # Standalone table update if JSON artifact was not on disk
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

    # 2. Upload ATC results to MinIO S3
    try:
        from utils.s3_storage import upload_bytes as s3_upload_bytes
        s3_upload_bytes(f"bids/{safe_bid_no}/atc_compliance.json", json.dumps(atc_result, default=str).encode("utf-8"), content_type="application/json")
        log.info(f"[Tier 3] Streamed atc_compliance.json to MinIO for {safe_bid_no}")
    except Exception as s3_err:
        log.warning(f"[Tier 3] MinIO upload failed for {safe_bid_no}: {s3_err}")

    # 3. Mark Redis key as completed

    try:
        r = _get_redis_client()
        r.set(f"gem:seen:{safe_bid_no}", "completed", ex=86400 * 30)
    except Exception as redis_err:
        log.warning(f"[Tier 3] Redis status update failed: {redis_err}")

    log.info(f"[Tier 3] Tender {safe_bid_no} 100% processed and indexed.")
    return {"status": "completed", "bid_no": safe_bid_no, "has_atc": atc_result.get("has_atc", False)}
