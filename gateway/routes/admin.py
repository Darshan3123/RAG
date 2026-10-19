# =========================================================================
# gateway/routes/admin.py
# On-Demand Scraper Triggers & Celery Task Telemetry Routes
# =========================================================================
from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, status

from gateway.schemas import ScrapeOnDemandRequest, TaskStatusResponse
from tasks.celery_app import app as celery_app
from tasks.tier1_scraper import scrape_category, scrape_single_bid
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1", tags=["Crawler Management & Tasks"])
log = get_logger("gateway_admin")


@router.post(
    "/bids/scrape-ondemand",
    response_model=TaskStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger On-Demand Crawl",
)
async def trigger_ondemand_scrape(request: ScrapeOnDemandRequest):
    """
    Enqueues a crawler task to the Redis `scraping_queue` in ~2-3ms:
    - If `bid_no` is provided: Searches specifically for that tender.
    - If `category` is provided: Crawls up to `target_count` new tenders for that category.
    Returns the Celery `task_id` for client polling.
    """
    try:
        if request.bid_no:
            task = scrape_single_bid.delay(bid_no=request.bid_no)
            log.info(f"Enqueued single bid scrape: {request.bid_no} -> task_id={task.id}")
        else:
            cat = request.category or "Product Bid/RAs"
            count = request.target_count or 1
            task = scrape_category.delay(bid_type=cat, target_count=count)
            log.info(f"Enqueued category scrape: {cat} (count={count}) -> task_id={task.id}")

        return TaskStatusResponse(
            task_id=task.id,
            status="PENDING",
            ready=False,
            result=None,
        )
    except Exception as e:
        log.error(f"Failed to enqueue scrape task: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger on-demand crawl: {str(e)}",
        )


@router.get(
    "/tasks/{task_id}",
    response_model=TaskStatusResponse,
    summary="Poll Celery Task Status",
)
async def get_task_status(task_id: str):
    """
    Inspects execution state of any background Celery task (PENDING, STARTED, SUCCESS, FAILURE).
    """
    try:
        res = AsyncResult(task_id, app=celery_app)
        task_status = res.status
        is_ready = res.ready()
        task_result = None

        if is_ready:
            try:
                task_result = res.result
                if isinstance(task_result, Exception):
                    task_result = str(task_result)
            except Exception:
                task_result = "Result retrieval error"

        return TaskStatusResponse(
            task_id=task_id,
            status=task_status,
            ready=is_ready,
            result=task_result,
        )
    except Exception as e:
        log.error(f"Error checking status for task {task_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check task status: {str(e)}",
        )
