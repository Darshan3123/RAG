# =========================================================================
# gateway/routes/health.py
# System Health & Root Telemetry Routes
# =========================================================================
import time
from fastapi import APIRouter, Response, status
import redis

from config.settings import REDIS_URL
from gateway.schemas import HealthResponse
from storage.postgres_db import get_db_cursor
from utils.logger import get_logger
from utils.s3_storage import ensure_bucket_exists

router = APIRouter(tags=["Health & Status"])
log = get_logger("gateway_health")

_START_TIME = time.time()


@router.get("/", summary="Gateway Root Welcome")
async def root():
    return {
        "service": "GeMBridge Enterprise Procurement Intelligence Platform",
        "version": "3.0.0",
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "endpoints": {
            "health": "/health",
            "list_bids": "GET /api/v1/bids",
            "get_bid": "GET /api/v1/bids/{bid_no}",
            "get_bid_pdf": "GET /api/v1/bids/{bid_no}/pdf",
            "ask_rag": "POST /api/v1/bids/ask",
            "scrape_ondemand": "POST /api/v1/bids/scrape-ondemand",
            "task_status": "GET /api/v1/tasks/{task_id}",
        },
    }


@router.get("/health", response_model=HealthResponse, summary="System Health Check")
async def health_check(response: Response):
    """
    Checks connectivity to:
      1. PostgreSQL database pool
      2. Redis task broker
      3. MinIO S3 storage
    """
    db_status = "unknown"
    redis_status = "unknown"
    minio_status = "unknown"

    # 1. PostgreSQL Check
    try:
        with get_db_cursor(commit=False) as cur:
            cur.execute("SELECT 1;")
            db_status = "healthy"
    except Exception as e:
        log.error(f"PostgreSQL health check failed: {e}")
        db_status = f"unhealthy: {e}"

    # 2. Redis Check
    try:
        r = redis.Redis.from_url(REDIS_URL, socket_timeout=2)
        if r.ping():
            redis_status = "healthy"
        else:
            redis_status = "unresponsive"
    except Exception as e:
        log.error(f"Redis health check failed: {e}")
        redis_status = f"unhealthy: {e}"

    # 3. MinIO Check
    try:
        if ensure_bucket_exists():
            minio_status = "healthy"
        else:
            minio_status = "unavailable"
    except Exception as e:
        log.error(f"MinIO health check failed: {e}")
        minio_status = f"unhealthy: {e}"

    is_all_healthy = (
        db_status == "healthy"
        and redis_status == "healthy"
        and minio_status == "healthy"
    )

    overall_status = "healthy" if is_all_healthy else "degraded"
    if not is_all_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status=overall_status,
        database=db_status,
        redis=redis_status,
        minio=minio_status,
        version="3.0.0",
        uptime_seconds=round(time.time() - _START_TIME, 2),
    )
