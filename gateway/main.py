# =========================================================================
# gateway/main.py
# GeMBridge REST API Gateway Application Entrypoint (v3.0.0)
# =========================================================================
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gateway.routes import admin, bids, health, rag
from storage.postgres_db import close_connection_pool, get_connection_pool
from utils.logger import get_logger

log = get_logger("gateway_app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage lifecycle of connection pools and external services.
    """
    log.info("Starting up GeMBridge REST API Gateway...")
    try:
        pool = get_connection_pool(minconn=2, maxconn=10)
        log.info(f"Database connection pool initialized ({pool})")
    except Exception as e:
        log.error(f"Failed to initialize database connection pool on startup: {e}")

    yield

    log.info("Shutting down GeMBridge REST API Gateway...")
    try:
        close_connection_pool()
        log.info("Database connection pool closed successfully.")
    except Exception as e:
        log.error(f"Error closing database connection pool: {e}")


app = FastAPI(
    title="GeMBridge Procurement Intelligence API",
    description=(
        "High-performance REST API Gateway for Indian Government e-Marketplace (GeM) "
        "tenders. Provides sub-5ms ACID relational queries, pgvector semantic search, "
        "presigned MinIO document downloads, and distributed Celery crawler orchestration."
    ),
    version="3.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# -------------------------------------------------------------------------
# CORS Configuration
# -------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------------------------------
# Telemetry & Request Timing Middleware
# -------------------------------------------------------------------------
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration_ms = (time.time() - start_time) * 1000
    response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
    if request.url.path not in ["/health", "/docs", "/openapi.json"]:
        log.info(f"{request.method} {request.url.path} -> {response.status_code} ({duration_ms:.2f}ms)")
    return response


# -------------------------------------------------------------------------
# Router Inclusions
# -------------------------------------------------------------------------
app.include_router(health.router)
app.include_router(bids.router)
app.include_router(rag.router)
app.include_router(admin.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("gateway.main:app", host="0.0.0.0", port=8000, reload=True)
