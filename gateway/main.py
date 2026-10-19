# =========================================================================
# gateway/main.py
# GeMBridge REST API Gateway (v3.0 Production Standard)
# Interactive Docs: http://localhost:8000/docs | ReDoc: http://localhost:8000/redoc
# =========================================================================
import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from gateway.routes import api_v1_router
from storage.postgres_db import close_connection_pool, get_connection_pool
from utils.logger import get_logger

log = get_logger("gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager: connects to database pool on startup and cleanly closes on shutdown."""
    log.info("Starting GeMBridge REST API Gateway (v3.0.0)...")
    try:
        get_connection_pool()
        log.info("PostgreSQL connection pool initialized for REST Gateway.")
    except Exception as e:
        log.warning(f"Database connection pool initialization warning: {e}")
    yield
    log.info("Shutting down GeMBridge REST API Gateway...")
    close_connection_pool()


app = FastAPI(
    title="GeMBridge REST API Gateway",
    version="3.0.0",
    description=(
        "High-performance unified REST API interface to Indian Government Procurement data "
        "from `bidplus.gem.gov.in`. Features 10 logical partitioned sub-resource modules, "
        "sub-5ms pgvector semantic search, MinIO S3 presigned document streaming, and Celery task dispatch."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# -------------------------------------------------------------------------
# CORS MIDDLEWARE
# -------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------------------------------
# GLOBAL STANDARDIZED EXCEPTION HANDLERS (Section 3 of Specification)
# -------------------------------------------------------------------------
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Formats all HTTP errors into the standard GeMBridge error schema."""
    error_code = "RESOURCE_NOT_FOUND" if exc.status_code == 404 else (
        "VALIDATION_ERROR" if exc.status_code == 422 else (
            "BAD_REQUEST" if exc.status_code == 400 else "INTERNAL_SERVER_ERROR"
        )
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error_code": error_code,
            "message": str(exc.detail),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catches unhandled exceptions and returns a consistent JSON payload."""
    log.error(f"Unhandled error at {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error_code": "INTERNAL_SERVER_ERROR",
            "message": "An internal error occurred while processing your request.",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    )


# -------------------------------------------------------------------------
# ROUTER MOUNTING
# -------------------------------------------------------------------------
app.include_router(api_v1_router)


# -------------------------------------------------------------------------
# TOP-LEVEL HEALTH & ROOT ENDPOINTS
# -------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def root_redirect():
    """Redirects root URL straight to interactive Swagger UI documentation."""
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["Health & Status"], summary="Gateway Health Check")
def health_check():
    """Returns gateway service status, version, and server timestamp."""
    return {
        "status": "healthy",
        "version": "3.0.0",
        "service": "GeMBridge REST API Gateway",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("gateway.main:app", host="0.0.0.0", port=8000, reload=True)
