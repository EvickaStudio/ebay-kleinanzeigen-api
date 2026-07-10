"""Listings with full details endpoint."""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Query
from fastapi_cache.decorator import cache

from ...api.dependencies import ScraperDep
from ...core.config import get_settings
from ...models import ApiErrorResponse, ApiResponse, DetailedListingItem

router = APIRouter(prefix="/v1", tags=["Listings"])
settings = get_settings()
LISTINGS_DETAILED_RESPONSES = {
    422: {
        "description": "Validation error from FastAPI for invalid query parameters.",
    },
    503: {
        "model": ApiErrorResponse,
        "description": "Kleinanzeigen temporarily blocked the host IP range.",
    },
}


@router.get(
    "/listings-detailed",
    response_model=ApiResponse[list[DetailedListingItem]],
    responses=LISTINGS_DETAILED_RESPONSES,
)
@cache(expire=settings.cache_ttl_seconds)
async def search_listings_with_details(
    scraper: ScraperDep,
    raw_url: str | None = Query(
        None,
        description=(
            "Raw URL to scrape. If provided, overrides all other parameters "
            "except page parameters."
        ),
    ),
    query: str | None = Query(None, description="Search term"),
    location: str | None = Query(None, description="Location filter"),
    radius: int | None = Query(None, ge=1, le=100, description="Radius in km"),
    min_price: int | None = Query(None, ge=0, description="Minimum price filter"),
    max_price: int | None = Query(None, ge=0, description="Maximum price filter"),
    sort_by: Literal["lowest", "price", "preis", "highest", "teuerste"] | None = Query(
        None,
        description=(
            "Sort order: 'lowest'/'price'/'preis' (cheapest first), "
            "'highest'/'teuerste' (most expensive first), or omit for newest first"
        ),
    ),
    page_count: int = Query(1, ge=1, le=5, description="Number of pages to fetch"),
    start_page: int = Query(
        1, ge=1, le=200, description="Starting page number (default: 1)"
    ),
    max_concurrent_details: int = Query(
        10, ge=1, le=20, description="Max concurrent detail fetches"
    ),
) -> ApiResponse[list[DetailedListingItem]]:
    started_at = time.perf_counter()
    combined = await scraper.fetch_listings_with_details(
        raw_url=raw_url,
        query=query,
        location=location,
        radius=radius,
        min_price=min_price,
        max_price=max_price,
        sort_by=sort_by,
        page_count=page_count,
        start_page=start_page,
        max_concurrent_details=max_concurrent_details,
    )

    elapsed = round(time.perf_counter() - started_at, 3)
    return ApiResponse(success=True, data=combined, time_taken=elapsed)
