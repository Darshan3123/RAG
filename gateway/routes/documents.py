# =========================================================================
# gateway/routes/documents.py
# Group 5: Document Storage & Streaming APIs (MinIO S3 Presigned URLs)
# =========================================================================
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from gateway.schemas import PresignedDownloadResponse
from storage.postgres_db import PostgresBidDatabase
from utils.logger import get_logger

router = APIRouter(prefix="/documents", tags=["4. Document Storage & Streaming"])
db = PostgresBidDatabase()
log = get_logger("documents_api")


@router.get("/{bid_no}/pdf", response_model=PresignedDownloadResponse, summary="Presigned Tender PDF Download Link")
def get_bid_pdf_link(
    bid_no: str,
    redirect: bool = Query(False, description="If true, issues an HTTP 307 redirect straight to S3 download stream"),
):
    """
    Returns a secure, time-limited presigned MinIO S3 URL (valid for 15 minutes = 900 seconds)
    for direct streaming from object storage without placing bandwidth overhead on the API server.
    """
    safe_bid_id = bid_no.replace("/", "_")
    
    # Check if bid exists
    dossier = db.get_bid_partition(safe_bid_id, "header")
    if not dossier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender '{bid_no}' not found in database.",
        )

    try:
        from utils.s3_storage import get_presigned_url
        download_url = get_presigned_url(f"bids/{safe_bid_id}/bid.pdf", expiry_seconds=900)
    except Exception as e:
        log.error(f"Failed to generate presigned URL for {safe_bid_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Storage service unavailable: {str(e)}",
        )

    if redirect:
        return RedirectResponse(url=download_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    return PresignedDownloadResponse(
        success=True,
        bid_no=dossier["bid_no"],
        document_type="bid_pdf",
        expires_in_seconds=900,
        download_url=download_url,
    )
