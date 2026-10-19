# =========================================================================
# gateway/routes/discovery.py
# Group 3: Discovery & Filter Aggregations (Types, Organizations & Geography)
# =========================================================================
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, status

from gateway.schemas import (
    BidTypesResponse,
    OrganizationsResponse,
    PincodeBidsResponse,
    StateBidsResponse,
    StatesResponse,
)
from storage.postgres_db import PostgresBidDatabase

router = APIRouter(tags=["2. Discovery & Aggregations"])
db = PostgresBidDatabase()


@router.get("/types", response_model=BidTypesResponse, summary="Bid Types Aggregation")
def get_bid_types():
    """
    Returns live aggregate tender counts and estimated budget values
    grouped by procurement bid type and category label.
    """
    return db.get_types_aggregation()


@router.get("/organizations", response_model=OrganizationsResponse, summary="Procuring Organizations Directory")
def get_organizations(
    min_bids: int = Query(1, ge=1, description="Minimum active bids threshold"),
    limit: int = Query(50, ge=1, le=200, description="Maximum organizations to return"),
):
    """
    Lists top procuring government organizations and their active tender counts
    and cumulative pipeline values.
    """
    return db.get_organizations_directory(min_bids=min_bids, limit=limit)


@router.get("/locations/states", response_model=StatesResponse, summary="State-Level Procurement Overview")
def get_states_overview():
    """
    Returns aggregate active tender counts and pipeline value grouped by Indian State or Central Ministry.
    """
    return db.get_states_aggregation()


@router.get("/locations/states/{state_name}/bids", response_model=StateBidsResponse, summary="Tenders by State")
def get_bids_by_state(
    state_name: str,
    limit: int = Query(50, ge=1, le=100, description="Maximum tenders to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """
    Returns tenders published by or requiring delivery in a specific Indian state.
    """
    return db.get_bids_by_state(state_name=state_name, limit=limit, offset=offset)


@router.get("/locations/pincode/{pincode}/bids", response_model=PincodeBidsResponse, summary="Pincode & Delivery Logistics Explorer")
def get_bids_by_pincode(
    pincode: str,
    limit: int = Query(50, ge=1, le=100, description="Maximum tenders to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """
    Discovers tenders requiring freight delivery to a specific 6-digit postal code,
    returning delivery warehouse addresses and turnaround days.
    """
    return db.get_bids_by_pincode(pincode=pincode, limit=limit, offset=offset)
