# =========================================================================
# gateway/schemas.py
# Pydantic Schemas for GeMBridge REST API Gateway (v3.0.0)
# =========================================================================
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


# -------------------------------------------------------------------------
# Health Check Models
# -------------------------------------------------------------------------
class HealthResponse(BaseModel):
    status: str = Field(..., description="Overall health state ('healthy', 'degraded', 'unhealthy')")
    database: str = Field(..., description="PostgreSQL connection status")
    redis: str = Field(..., description="Redis broker connection status")
    minio: str = Field(..., description="MinIO S3 storage status")
    version: str = Field("3.0.0", description="API version")
    uptime_seconds: Optional[float] = Field(None, description="Gateway process uptime in seconds")


# -------------------------------------------------------------------------
# Bid Query Models
# -------------------------------------------------------------------------
class BidSummaryCard(BaseModel):
    id: str
    bid_no: str
    product_type: Optional[str] = None
    organisation_name: Optional[str] = None
    department_name: Optional[str] = None
    total_items_count: Optional[int] = None
    total_quantity: Optional[float] = None
    estimated_value: Optional[float] = None
    emd_amount: Optional[float] = None
    end_datetime: Optional[Union[datetime, str]] = None
    days_remaining: Optional[int] = None
    status: Optional[str] = None

    model_config = {"extra": "allow"}


class BidListResponse(BaseModel):
    items: List[BidSummaryCard]
    total: int
    limit: int
    offset: int


class BidDetailResponse(BaseModel):
    id: str
    bid_no: str
    status: Optional[str] = None
    product_type: Optional[str] = None
    bid_type: Optional[str] = None
    organisation_name: Optional[str] = None
    department_name: Optional[str] = None
    start_datetime: Optional[Union[datetime, str]] = None
    end_datetime: Optional[Union[datetime, str]] = None
    opening_datetime: Optional[Union[datetime, str]] = None
    estimated_value: Optional[float] = None
    total_quantity: Optional[float] = None
    emd_amount: Optional[float] = None
    epbg_percentage: Optional[float] = None
    items: List[Dict[str, Any]] = []
    consignees: List[Dict[str, Any]] = []
    schedules: List[Dict[str, Any]] = []
    atc_checklist: Dict[str, List[str]] = {}
    physical_submissions: List[Dict[str, Any]] = []
    atc_telemetry: Optional[Dict[str, Any]] = None

    model_config = {"extra": "allow"}


# -------------------------------------------------------------------------
# RAG Query Models
# -------------------------------------------------------------------------
class RagQueryRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1000, description="Natural language search or question")
    top_k: int = Field(5, ge=1, le=50, description="Number of vector neighbors to retrieve")
    bid_id: Optional[str] = Field(None, description="Optional filter to scope search to a single tender ID or bid_no")
    synthesize_answer: bool = Field(False, description="When true, invokes LLM to formulate an answer from retrieved chunks")


class RagQueryResultChunk(BaseModel):
    id: int
    bid_id: str
    chunk_type: str
    chunk_text: str
    metadata: Dict[str, Any] = {}
    distance: float = Field(..., description="Cosine distance (0.0 = identical, 2.0 = opposite)")

    model_config = {"extra": "allow"}


class RagQueryResponse(BaseModel):
    query: str
    answer: Optional[str] = None
    count: int
    results: List[RagQueryResultChunk]


# -------------------------------------------------------------------------
# Admin & Crawl Task Models
# -------------------------------------------------------------------------
class ScrapeOnDemandRequest(BaseModel):
    bid_no: Optional[str] = Field(None, description="Specific GeM Bid Number (e.g., 'GEM/2026/B/7279373')")
    category: Optional[str] = Field("Product Bid/RAs", description="Category filter if scraping by category")
    target_count: int = Field(1, ge=1, le=50, description="Number of tenders to crawl if scraping by category")


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    ready: bool
    result: Optional[Any] = None
