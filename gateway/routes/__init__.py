# =========================================================================
# gateway/routes/__init__.py
# Central Router Aggregator for GeMBridge REST API Gateway (v3.0)
# =========================================================================
from fastapi import APIRouter, Depends

from config.settings import GATEWAY_ENABLE_ADMIN_ROUTES
from gateway.auth import require_internal_key
from gateway.routes.bids import router as bids_router
from gateway.routes.discovery import router as discovery_router
from gateway.routes.search import router as search_router
from gateway.routes.documents import router as documents_router
from gateway.routes.tasks import router as tasks_router
from gateway.routes.analytics import router as analytics_router

# All v1 routes require X-Internal-Key authentication
api_v1_router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(require_internal_key)],
)

api_v1_router.include_router(bids_router)
api_v1_router.include_router(discovery_router)
api_v1_router.include_router(search_router)
api_v1_router.include_router(documents_router)
api_v1_router.include_router(analytics_router)

# Mount dangerous crawling/scraper tasks only when admin routes are explicitly enabled (e.g. dev/internal)
if GATEWAY_ENABLE_ADMIN_ROUTES:
    api_v1_router.include_router(tasks_router)
