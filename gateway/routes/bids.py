# =========================================================================
# gateway/routes/bids.py
# Tender Query, Detail & MinIO Document Stream Routes
# =========================================================================
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse, RedirectResponse

from config.settings import DOWNLOAD_DIR
from gateway.schemas import BidDetailResponse, BidListResponse
from storage.postgres_db import PostgresBidDatabase
from utils.logger import get_logger
from utils.s3_storage import get_presigned_url, object_exists, upload_file

router = APIRouter(prefix="/api/v1/bids", tags=["Tenders & Documents"])
log = get_logger("gateway_bids")
db = PostgresBidDatabase()


@router.get("", response_model=BidListResponse, summary="List & Filter Tenders")
async def list_bids(
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    search: Optional[str] = Query(None, description="Search term matching bid number, organisation, or department"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (e.g. 'Active', 'Closed')"),
    is_expired: Optional[bool] = Query(False, description="Filter active vs expired bids"),
):
    """
    Sub-5ms paginated query returning lightweight tender summary cards.
    """
    try:
        items, total = db.list_bids(
            limit=limit,
            offset=offset,
            search=search,
            status=status_filter,
            is_expired=is_expired,
        )
        return BidListResponse(items=items, total=total, limit=limit, offset=offset)
    except Exception as e:
        log.error(f"Error querying bids list: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch bids list: {str(e)}",
        )


async def _resolve_bid(bid_identifier: str):
    try:
        bid = db.get_bid_by_no(bid_identifier)
        if not bid:
            alt_no = bid_identifier.replace("_", "/") if "_" in bid_identifier else bid_identifier.replace("/", "_")
            bid = db.get_bid_by_no(alt_no)

        if not bid:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tender '{bid_identifier}' not found in database",
            )
        return bid
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error retrieving bid {bid_identifier}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve tender: {str(e)}",
        )


async def _resolve_bid_pdf(bid_identifier: str):
    safe_bid_no = bid_identifier.replace("/", "_")
    s3_key = f"bids/{safe_bid_no}/bid.pdf"

    # 1. Check if file already exists in MinIO S3
    try:
        if object_exists(s3_key):
            presigned_url = get_presigned_url(s3_key, expiry_hours=24)
            return RedirectResponse(
                url=presigned_url,
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            )
    except Exception as s3_err:
        log.warning(f"MinIO check failed for {s3_key}: {s3_err}")

    # 2. Check if local file exists on disk
    local_pdf = Path(DOWNLOAD_DIR) / safe_bid_no / "bid.pdf"
    if local_pdf.exists():
        try:
            upload_file(s3_key, str(local_pdf), content_type="application/pdf")
            presigned_url = get_presigned_url(s3_key, expiry_hours=24)
            return RedirectResponse(
                url=presigned_url,
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            )
        except Exception as up_err:
            log.warning(f"Failed to upload local PDF to MinIO: {up_err}")
            return FileResponse(
                path=str(local_pdf),
                filename=f"{safe_bid_no}.pdf",
                media_type="application/pdf",
            )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"PDF document for tender '{bid_identifier}' is not available",
    )


@router.get("/detail", response_model=BidDetailResponse, summary="Get Full Tender Details by Query Param")
async def get_bid_by_query(bid_no: str = Query(..., description="Tender Bid Number or ID")):
    return await _resolve_bid(bid_no)


@router.get("/download-pdf", summary="Download Tender PDF Document by Query Param")
async def get_bid_pdf_by_query(bid_no: str = Query(..., description="Tender Bid Number or ID")):
    return await _resolve_bid_pdf(bid_no)


@router.get("/{bid_id}/pdf", summary="Download Tender PDF Document")
async def get_bid_pdf(bid_id: str):
    """
    Issues an HTTP 307 Temporary Redirect to a presigned MinIO S3 URL (24h validity).
    """
    return await _resolve_bid_pdf(bid_id)


@router.get("/{bid_id:path}", response_model=BidDetailResponse, summary="Get Full Tender Details")
async def get_bid(bid_id: str):
    """
    Retrieve complete tender record including:
    - Master specifications & dates
    - Child line items
    - Consignees & delivery locations
    - Evaluation schedules
    - ATC compliance checklist & physical submissions
    - AI Telemetry analysis
    """
    return await _resolve_bid(bid_id)
