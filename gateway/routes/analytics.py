# =========================================================================
# gateway/routes/analytics.py
# Group 7: Analytics & System Telemetry APIs
# =========================================================================
from fastapi import APIRouter

from gateway.schemas import AnalyticsAITelemetryResponse, AnalyticsOverviewResponse
from storage.postgres_db import PostgresBidDatabase

router = APIRouter(prefix="/analytics", tags=["6. Analytics & Telemetry"])
db = PostgresBidDatabase()


@router.get("/overview", response_model=AnalyticsOverviewResponse, summary="Overall System Health & Pipeline KPIs")
def get_analytics_overview():
    """
    Real-time KPI metrics aggregating total tenders scraped, active ongoing tenders,
    expired tenders, total estimated pipeline INR value, and total delivery locations.
    """
    return db.get_analytics_overview()


@router.get("/ai-telemetry", response_model=AnalyticsAITelemetryResponse, summary="AI & OCR Telemetry Audit")
def get_ai_telemetry():
    """
    Aggregates total token consumption, Mistral OCR page count, and financial costs
    in USD and INR across all Gemini AI compliance analyses.
    """
    return db.get_analytics_ai_telemetry()
