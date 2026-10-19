# =========================================================================
# gateway/schemas.py
# Pydantic Schemas for GeMBridge REST API Gateway (v3.0)
# =========================================================================
from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# -------------------------------------------------------------------------
# STANDARD ERROR & WRAPPER SCHEMAS
# -------------------------------------------------------------------------
class StandardErrorResponse(BaseModel):
    success: bool = False
    error_code: str
    message: str
    timestamp: str


# -------------------------------------------------------------------------
# MASTER DOSSIER SCHEMAS (Group 1)
# -------------------------------------------------------------------------
class TimingSchema(BaseModel):
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    bid_opening_datetime: Optional[str] = None
    bid_offer_validity_days: Optional[int] = None
    days_remaining: Optional[float] = None


class BuyerSchema(BaseModel):
    ministry_state_name: Optional[str] = None
    department_name: Optional[str] = None
    organisation_name: Optional[str] = None
    office_name: Optional[str] = None


class FinancialsSchema(BaseModel):
    estimated_value: Optional[float] = None
    emd_required: Optional[bool] = False
    emd_amount: Optional[float] = None
    emd_advisory_bank: Optional[str] = None
    epbg_required: Optional[bool] = False
    epbg_percent: Optional[float] = None


class PolicySchema(BaseModel):
    mse_preference: Optional[bool] = False
    mse_price_band_percent: Optional[float] = None
    mse_max_quantity_percent: Optional[float] = None
    mse_relaxation: Optional[bool] = False
    startup_relaxation: Optional[bool] = False
    mii_preference: Optional[bool] = False


class ItemSchema(BaseModel):
    item_index: int
    item_category: str
    quantity: Optional[float] = None
    source: Optional[str] = "pdf"
    specifications: Optional[Dict[str, Any]] = None


class ConsigneeSchema(BaseModel):
    officer_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    quantity: Optional[float] = None
    delivery_days: Optional[int] = None
    is_lumpsum: Optional[bool] = False


class PhysicalSubmissionSchema(BaseModel):
    item_name: str
    deadline: Optional[str] = None
    in_favor_of: Optional[str] = None
    payable_at: Optional[str] = None
    delivery_address: Optional[str] = None
    original_clause_text: Optional[str] = None


class DocumentsSchema(BaseModel):
    bid_pdf_download_url: Optional[str] = None
    atc_compliance_url: Optional[str] = None


class BidDossierResponse(BaseModel):
    success: bool = True
    bid_no: str
    ra_no: Optional[str] = None
    bid_type: Optional[str] = None
    product_type: Optional[str] = None
    status: Optional[str] = "ongoing"
    timing: Optional[TimingSchema] = None
    buyer: Optional[BuyerSchema] = None
    financials: Optional[FinancialsSchema] = None
    policy: Optional[PolicySchema] = None
    required_documents: Optional[List[str]] = Field(default_factory=list)
    items: Optional[List[ItemSchema]] = None
    consignees: Optional[List[ConsigneeSchema]] = None
    atc_checklist: Optional[Dict[str, List[str]]] = None
    physical_submissions: Optional[List[PhysicalSubmissionSchema]] = None
    documents: Optional[DocumentsSchema] = None


class PaginationMeta(BaseModel):
    total_records: int
    current_page: int
    limit: int
    total_pages: int


class BidCard(BaseModel):
    bid_no: str
    bid_type: Optional[str] = None
    product_type: Optional[str] = None
    status: Optional[str] = "ongoing"
    title_item: Optional[str] = None
    total_quantity: Optional[float] = None
    estimated_value: Optional[float] = None
    emd_amount: Optional[float] = None
    department: Optional[str] = None
    organisation: Optional[str] = None
    state: Optional[str] = None
    end_datetime: Optional[str] = None
    days_remaining: Optional[float] = None


class BidListResponse(BaseModel):
    success: bool = True
    pagination: PaginationMeta
    data: List[BidCard]


# -------------------------------------------------------------------------
# PARTITIONED SUB-RESOURCE SCHEMAS (Group 2)
# -------------------------------------------------------------------------
class HeaderPartitionResponse(BaseModel):
    success: bool = True
    bid_no: str
    ra_no: Optional[str] = None
    bid_type: Optional[str] = None
    product_type: Optional[str] = None
    status: Optional[str] = None
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    bid_opening_datetime: Optional[str] = None
    bid_offer_validity_days: Optional[int] = None
    bid_duration_days: Optional[float] = None
    days_remaining: Optional[float] = None
    is_expired: bool = False


class BuyerPartitionResponse(BaseModel):
    success: bool = True
    bid_no: str
    ministry_state_name: Optional[str] = None
    department_name: Optional[str] = None
    organisation_name: Optional[str] = None
    office_name: Optional[str] = None


class ItemsPartitionResponse(BaseModel):
    success: bool = True
    bid_no: str
    total_items_count: int
    total_quantity: Optional[float] = None
    items: List[ItemSchema]


class ConsigneesPartitionResponse(BaseModel):
    success: bool = True
    bid_no: str
    total_locations: int
    consignees: List[ConsigneeSchema]


class EMDDetailSchema(BaseModel):
    required: bool = False
    amount: Optional[float] = None
    percent_of_estimated_value: Optional[float] = None
    advisory_bank: Optional[str] = None
    exemption_allowed_for_mse: bool = False
    exemption_terms: Optional[str] = None


class EPBGDetailSchema(BaseModel):
    required: bool = False
    percent: Optional[float] = None
    advisory_bank: Optional[str] = None
    duration_months: Optional[int] = None


class FinancialsPartitionResponse(BaseModel):
    success: bool = True
    bid_no: str
    estimated_value: Optional[float] = None
    currency: str = "INR"
    is_high_value: bool = False
    emd: EMDDetailSchema
    epbg: EPBGDetailSchema


class PolicyPartitionResponse(BaseModel):
    success: bool = True
    bid_no: str
    mse_preference: bool = False
    mse_price_band_percent: Optional[float] = None
    mse_max_quantity_percent: Optional[float] = None
    mse_relaxation: bool = False
    startup_relaxation: bool = False
    mii_preference: bool = False
    mii_price_band_percent: Optional[float] = None
    allow_only_class_1_2: bool = False


class DocumentsPartitionResponse(BaseModel):
    success: bool = True
    bid_no: str
    show_docs_to_all_bidders: bool = False
    mandatory_documents_count: int
    required_documents: List[str]


class ATCPartitionResponse(BaseModel):
    success: bool = True
    bid_no: str
    has_atc: bool = False
    domains: Dict[str, List[str]]


class SubmissionsPartitionResponse(BaseModel):
    success: bool = True
    bid_no: str
    submissions_count: int
    items: List[PhysicalSubmissionSchema]


# -------------------------------------------------------------------------
# DISCOVERY & AGGREGATIONS SCHEMAS (Group 3)
# -------------------------------------------------------------------------
class BidTypeItem(BaseModel):
    type_name: str
    category_label: Optional[str] = None
    active_bids_count: int
    total_estimated_value: float


class BidTypesResponse(BaseModel):
    success: bool = True
    total_active_bids: int
    types: List[BidTypeItem]


class OrganizationItem(BaseModel):
    organisation_name: str
    department_name: Optional[str] = None
    state: Optional[str] = None
    active_bids_count: int
    total_pipeline_value: float


class OrganizationsResponse(BaseModel):
    success: bool = True
    total_organizations: int
    organizations: List[OrganizationItem]


class StateItem(BaseModel):
    state: str
    active_bids_count: int
    total_pipeline_value: float


class StatesResponse(BaseModel):
    success: bool = True
    total_states: int
    states: List[StateItem]


class StateBidItem(BaseModel):
    bid_no: str
    organisation: Optional[str] = None
    title_item: Optional[str] = None
    estimated_value: Optional[float] = None
    end_datetime: Optional[str] = None


class StateBidsResponse(BaseModel):
    success: bool = True
    state: str
    active_tenders_count: int
    bids: List[StateBidItem]


class PincodeBidItem(BaseModel):
    bid_no: str
    organisation: Optional[str] = None
    delivery_address: Optional[str] = None
    quantity: Optional[float] = None
    delivery_days: Optional[int] = None


class PincodeBidsResponse(BaseModel):
    success: bool = True
    pincode: str
    city: Optional[str] = None
    matching_tenders: int
    bids: List[PincodeBidItem]


# -------------------------------------------------------------------------
# SEARCH SCHEMAS (Group 4)
# -------------------------------------------------------------------------
class QuickSearchResponse(BaseModel):
    success: bool = True
    query: str
    suggestions: Dict[str, Any]


class KeywordMatchItem(BaseModel):
    bid_no: str
    matched_category: Optional[str] = None
    organisation: Optional[str] = None
    quantity: Optional[float] = None
    estimated_value: Optional[float] = None


class KeywordSearchResponse(BaseModel):
    success: bool = True
    query: str
    matches: List[KeywordMatchItem]


class SemanticSearchRequest(BaseModel):
    query: str
    top_k: int = 5
    filter_state: Optional[str] = None


class SemanticSearchResultItem(BaseModel):
    bid_no: str
    chunk_type: str
    similarity_score: float
    distance: float
    matching_text: str
    metadata: Optional[Dict[str, Any]] = None


class SemanticSearchResponse(BaseModel):
    success: bool = True
    query: str
    retrieval_latency_ms: float
    results_count: int
    results: List[SemanticSearchResultItem]


# -------------------------------------------------------------------------
# DOCUMENT STORAGE SCHEMAS (Group 5)
# -------------------------------------------------------------------------
class PresignedDownloadResponse(BaseModel):
    success: bool = True
    bid_no: str
    document_type: str = "bid_pdf"
    expires_in_seconds: int = 900
    download_url: str


# -------------------------------------------------------------------------
# CELERY TASK SCHEMAS (Group 6)
# -------------------------------------------------------------------------
class ScrapeTaskRequest(BaseModel):
    bid_no: str


class ScrapeTaskResponse(BaseModel):
    success: bool = True
    task_id: str
    status: str = "QUEUED"
    queue: str = "scraping_queue"
    message: str


class TaskStatusResponse(BaseModel):
    success: bool = True
    task_id: str
    status: str
    result: Optional[Any] = None


# -------------------------------------------------------------------------
# ANALYTICS & TELEMETRY SCHEMAS (Group 7)
# -------------------------------------------------------------------------
class OverviewMetrics(BaseModel):
    total_tenders_scraped: int
    active_ongoing_tenders: int
    expired_tenders: int
    total_estimated_pipeline_inr: float
    total_items_procured: float
    total_delivery_locations: int
    average_emd_amount_inr: float


class AnalyticsOverviewResponse(BaseModel):
    success: bool = True
    metrics: OverviewMetrics


class AITelemetryMetrics(BaseModel):
    total_tenders_analyzed: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    total_cost_inr: float
    average_cost_per_bid_inr: float
    average_latency_seconds: float


class AnalyticsAITelemetryResponse(BaseModel):
    success: bool = True
    ai_telemetry: AITelemetryMetrics
