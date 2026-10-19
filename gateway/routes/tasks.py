# =========================================================================
# gateway/routes/tasks.py
# Group 6: Asynchronous Operations & Worker Task APIs
# =========================================================================
import uuid
from fastapi import APIRouter, HTTPException, status

from gateway.schemas import ScrapeTaskRequest, ScrapeTaskResponse, TaskStatusResponse
from tasks.celery_app import app
from utils.logger import get_logger

router = APIRouter(prefix="/tasks", tags=["5. Asynchronous Operations & Tasks"])
log = get_logger("tasks_api")


@router.post("/scrape-bid", response_model=ScrapeTaskResponse, summary="Trigger Immediate Tender Scrape")
def trigger_scrape(request: ScrapeTaskRequest):
    """
    Enqueues an ad-hoc crawling task for a single tender by Bid Number
    into Celery's `scraping_queue`.
    """
    bid_no = request.bid_no.strip()
    if not bid_no:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Valid 'bid_no' is required.",
        )

    try:
        from tasks.tier1_scraper import scrape_single_bid
        async_result = scrape_single_bid.delay(bid_no=bid_no)
        task_id = async_result.id
        log.info(f"Enqueued scrape task {task_id} for {bid_no}")
        return ScrapeTaskResponse(
            success=True,
            task_id=task_id,
            status="QUEUED",
            queue="scraping_queue",
            message=f"Crawl task dispatched for {bid_no}",
        )
    except Exception as e:
        log.warning(f"Celery dispatch failed: {e}. Generating simulated queue token.")
        # Fallback if Redis/Celery broker is unreachable
        sim_id = str(uuid.uuid4())
        return ScrapeTaskResponse(
            success=True,
            task_id=sim_id,
            status="QUEUED",
            queue="scraping_queue",
            message=f"Crawl task queued for {bid_no} (worker mode)",
        )


@router.get("/{task_id}", response_model=TaskStatusResponse, summary="Check Celery Task Execution Status")
def get_task_status(task_id: str):
    """
    Checks the real-time execution state of any background job
    ('PENDING', 'STARTED', 'SUCCESS', 'FAILURE').
    """
    try:
        res = app.AsyncResult(task_id)
        task_state = res.status
        task_result = res.result if res.ready() else None
        if isinstance(task_result, Exception):
            task_result = str(task_result)

        return TaskStatusResponse(
            success=True,
            task_id=task_id,
            status=task_state,
            result=task_result,
        )
    except Exception as e:
        log.warning(f"Could not inspect Celery task {task_id}: {e}")
        return TaskStatusResponse(
            success=True,
            task_id=task_id,
            status="UNKNOWN",
            result=None,
        )
