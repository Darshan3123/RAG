# =========================================================================
# gateway/routes/bids.py
# Group 1 & Group 2: Master Dossier, Paginated Filter Table & Sub-Resource Partitions
# =========================================================================
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status

from gateway.schemas import (
    ATCPartitionResponse,
    BidDossierResponse,
    BidListResponse,
    BuyerPartitionResponse,
    ConsigneesPartitionResponse,
    DocumentsPartitionResponse,
    FinancialsPartitionResponse,
    HeaderPartitionResponse,
    ItemsPartitionResponse,
    PolicyPartitionResponse,
    SubmissionsPartitionResponse,
)
from storage.postgres_db import PostgresBidDatabase

router = APIRouter(prefix="/bids", tags=["1. Master Tenders & Partitions"])
db = PostgresBidDatabase()


# -------------------------------------------------------------------------
# GROUP 1: MASTER APIS
# -------------------------------------------------------------------------
@router.get("", response_model=BidListResponse, summary="Master Paginated & Filterable Tender List")
def list_bids(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by status (e.g. ongoing, cancelled)"),
    bid_type: Optional[str] = Query(None, description="Filter by bid type (e.g. 'Product Bid/RAs')"),
    product_type: Optional[str] = Query(None, description="Filter by product category (e.g. 'Product')"),
    min_value: Optional[float] = Query(None, description="Minimum estimated tender value in INR"),
    max_value: Optional[float] = Query(None, description="Maximum estimated tender value in INR"),
    state: Optional[str] = Query(None, description="Filter by procuring state or ministry name"),
    is_expired: Optional[bool] = Query(None, description="Filter by expired flag (true/false)"),
    search: Optional[str] = Query(None, description="Fuzzy search on Bid No, Department, or Organisation"),
):
    """
    High-speed paginated tender listing with composite multi-field filters.
    Optimized for data tables and search dashboards (< 5ms).
    """
    return db.list_bids_v3(
        page=page,
        limit=limit,
        status=status,
        bid_type=bid_type,
        product_type=product_type,
        min_value=min_value,
        max_value=max_value,
        state=state,
        is_expired=is_expired,
        search=search,
    )


@router.get("/{bid_no}", response_model=BidDossierResponse, summary="Get Complete Tender Dossier")
def get_bid_dossier(
    bid_no: str,
    include: str = Query("all", description="Comma-separated partitions to include: all, items, consignees, atc, submissions, documents"),
):
    """
    Returns the complete, exhaustive master tender dossier across all 10 normalized tables.
    Includes technical specifications, delivery consignees, AI compliance checklist, and S3 URLs.
    """
    dossier = db.get_bid_dossier(bid_no, include=include)
    if not dossier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender '{bid_no}' was not found in database.",
        )
    return dossier


@router.get("/{bid_no}/raw", summary="Get Original Scraped Raw JSON Backup")
def get_bid_raw(bid_no: str):
    """
    Returns the raw unaltered scraped JSON payload stored in the database's `raw_data` column.
    """
    raw_doc = db.get_bid_raw(bid_no)
    if not raw_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Raw document for tender '{bid_no}' was not found.",
        )
    return raw_doc


# -------------------------------------------------------------------------
# GROUP 2: PARTITIONED SUB-RESOURCE APIS (Frontend Tabs & B2B Feeds)
# -------------------------------------------------------------------------
@router.get("/{bid_no}/header", response_model=HeaderPartitionResponse, summary="P1: Lifecycle & Identity Partition")
def get_bid_header(bid_no: str):
    """Lifecycle timings, dates, offer validity days, days remaining, and status."""
    part = db.get_bid_partition(bid_no, "header")
    if not part:
        raise HTTPException(status_code=404, detail=f"Tender '{bid_no}' not found.")
    return part


@router.get("/{bid_no}/buyer", response_model=BuyerPartitionResponse, summary="P2: Buyer & Governance Partition")
def get_bid_buyer(bid_no: str):
    """Central Ministry, State Government, Department, Procuring Organisation, and Office."""
    part = db.get_bid_partition(bid_no, "buyer")
    if not part:
        raise HTTPException(status_code=404, detail=f"Tender '{bid_no}' not found.")
    return part


@router.get("/{bid_no}/items", response_model=ItemsPartitionResponse, summary="P3: Items & Technical Specs Partition")
def get_bid_items(bid_no: str):
    """Product catalog categories, requested quantities, units, and JSONB technical specifications."""
    part = db.get_bid_partition(bid_no, "items")
    if not part:
        raise HTTPException(status_code=404, detail=f"Tender '{bid_no}' not found.")
    return part


@router.get("/{bid_no}/consignees", response_model=ConsigneesPartitionResponse, summary="P4: Logistics & Consignees Partition")
def get_bid_consignees(bid_no: str):
    """Delivery warehouse locations, consignee officers, delivery days, and regional pincodes."""
    part = db.get_bid_partition(bid_no, "consignees")
    if not part:
        raise HTTPException(status_code=404, detail=f"Tender '{bid_no}' not found.")
    return part


@router.get("/{bid_no}/financials", response_model=FinancialsPartitionResponse, summary="P5: Financials & EMD / Bank Guarantees Partition")
def get_bid_financials(bid_no: str):
    """Estimated value, EMD amount, advisory bank, exemption rules, and ePBG requirements."""
    part = db.get_bid_partition(bid_no, "financials")
    if not part:
        raise HTTPException(status_code=404, detail=f"Tender '{bid_no}' not found.")
    return part


@router.get("/{bid_no}/policy", response_model=PolicyPartitionResponse, summary="P6: Policy Preferences Partition")
def get_bid_policy(bid_no: str):
    """MSE purchase preference %, Startup waiver, Make in India local class requirements."""
    part = db.get_bid_partition(bid_no, "policy")
    if not part:
        raise HTTPException(status_code=404, detail=f"Tender '{bid_no}' not found.")
    return part


@router.get("/{bid_no}/documents", response_model=DocumentsPartitionResponse, summary="P7: Mandatory Documents Required Partition")
def get_bid_documents(bid_no: str):
    """Pre-bid document checklist outlining all mandatory uploads requested by the buyer."""
    part = db.get_bid_partition(bid_no, "documents")
    if not part:
        raise HTTPException(status_code=404, detail=f"Tender '{bid_no}' not found.")
    return part


@router.get("/{bid_no}/atc", response_model=ATCPartitionResponse, summary="P8: ATC AI Compliance Checklist Partition")
def get_bid_atc(bid_no: str):
    """8-domain structured compliance checklist analyzed by Gemini AI."""
    part = db.get_bid_partition(bid_no, "atc")
    if not part:
        raise HTTPException(status_code=404, detail=f"Tender '{bid_no}' not found.")
    return part


@router.get("/{bid_no}/submissions", response_model=SubmissionsPartitionResponse, summary="P9: Physical Submissions Partition")
def get_bid_submissions(bid_no: str):
    """Offline physical submissions (Demand Drafts, samples, payee names, delivery addresses, deadlines)."""
    part = db.get_bid_partition(bid_no, "submissions")
    if not part:
        raise HTTPException(status_code=404, detail=f"Tender '{bid_no}' not found.")
    return part
