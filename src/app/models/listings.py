from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from .metrics import PerformanceMetrics


class Price(BaseModel):
    amount: float = Field(..., ge=0)
    currency: str = Field(..., min_length=1)
    negotiable: bool = Field(default=False)


class Location(BaseModel):
    zip: str = Field(default="")
    city: str = Field(default="")
    state: str | None = None


class Seller(BaseModel):
    name: str | None = None
    since: str | None = None
    type: str = Field(default="private")
    badges: list[str] = Field(default_factory=list)


class ListingDetail(BaseModel):
    id: str = Field(..., min_length=1)
    categories: list[str] = Field(default_factory=list)
    title: str = Field(default="")
    status: str = Field(default="active")
    price: Price
    delivery: str | None = None
    delivery_cost: str | None = None
    location: Location
    views: int | None = Field(default=None, ge=0)
    description: str | None = None
    images: list[str] = Field(default_factory=list)
    details: dict[str, str] = Field(default_factory=dict)
    features: list[str] = Field(default_factory=list)
    seller: Seller
    extra_info: dict[str, str | None] = Field(default_factory=dict)


class ListingSummary(BaseModel):
    ad_id: str = Field(..., alias="adid")
    url: str
    title: str
    price: float | None = Field(default=None, ge=0)
    currency: str | None = None
    negotiable: bool = Field(default=False)
    is_top: bool = Field(default=False)
    description_snippet: str | None = Field(default=None, alias="description")

    model_config = {
        "populate_by_name": True,
        "from_attributes": True,
    }

    @field_validator("price", mode="before")
    @classmethod
    def _coerce_price(cls, value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None


class DetailedListingItem(BaseModel):
    """A listing summary paired with its full detail, returned by /listings-detailed."""

    summary: ListingSummary
    detail: ListingDetail


class PaginationMetadata(BaseModel):
    """Metadata about pagination and search results."""

    pages_requested: int = Field(..., ge=1, description="Number of pages requested")
    pages_fetched: int = Field(
        ..., ge=0, description="Number of pages actually processed"
    )
    start_page: int = Field(default=1, ge=1, description="First processed page")
    end_page: int = Field(..., ge=1, description="Last processed page")
    total_available_results: int | None = Field(
        default=None,
        ge=0,
        description="Total results available from search (if detected)",
    )
    results_per_page: int = Field(default=25, ge=1, description="Results per page")
    duplicates_removed: int = Field(
        default=0, ge=0, description="Number of duplicate listings removed"
    )


class ListingsResponse(BaseModel):
    success: bool = True
    results: list[ListingSummary] = Field(default_factory=list)
    total_results: int = Field(..., ge=0)
    pagination: PaginationMetadata | None = None
    metrics: PerformanceMetrics | None = Field(
        default=None, description="Per-page fetch timing metrics"
    )
    time_taken: float = Field(..., ge=0)
