import datetime as dt
from fractions import Fraction
from typing import Any

from pydantic import BaseModel, Field

from comps_pipeline.models.cell import Cell

SQFT_PER_ACRE = 43560  # unit conversion, not a business rule

# Standard comp fields a CSV column can be mapped to (see config/column_mapping.yaml).
STANDARD_FIELDS = (
    "mls_number",
    "status",
    "close_price",
    "close_date",
    "list_price",
    "living_area",
    "year_built",
    "lot_size_sqft",
    "lot_size_acres",
    "bedrooms",
    "baths_full",
    "baths_half",
    "subdivision_raw",
    "latitude",
    "longitude",
    "reported_distance_miles",
    "foundation_type",
    "public_remarks",
)


def lot_acres(sqft: int | None, acres: float | None) -> Fraction | None:
    """Exact lot size in acres. Square feet win when both are given (more precise)."""
    if sqft is not None:
        return Fraction(sqft, SQFT_PER_ACRE)
    if acres is not None:
        return Fraction(str(acres))
    return None


def total_baths(full: int | None, half: int | None) -> Fraction | None:
    """Full + 0.5 x half. Unknown half baths with known full baths count as unknown."""
    if full is None or half is None:
        return None
    return full + Fraction(half, 2)


class Comp(BaseModel):
    mls_number: str
    source_row: int  # 1-based data row in the input CSV, for traceability
    pool: str | None = None  # "sold" | "listing", from status (config status.*)
    status: Cell[str] = Field(default_factory=Cell)
    close_price: Cell[int] = Field(default_factory=Cell)
    close_date: Cell[dt.date] = Field(default_factory=Cell)
    list_price: Cell[int] = Field(default_factory=Cell)
    living_area: Cell[int] = Field(default_factory=Cell)
    year_built: Cell[int] = Field(default_factory=Cell)
    lot_size_sqft: Cell[int] = Field(default_factory=Cell)
    lot_size_acres: Cell[float] = Field(default_factory=Cell)
    bedrooms: Cell[int] = Field(default_factory=Cell)
    baths_full: Cell[int] = Field(default_factory=Cell)
    baths_half: Cell[int] = Field(default_factory=Cell)
    subdivision_raw: Cell[str] = Field(default_factory=Cell)
    subdivision_normalized: Cell[str] = Field(default_factory=Cell)
    latitude: Cell[float] = Field(default_factory=Cell)
    longitude: Cell[float] = Field(default_factory=Cell)
    reported_distance_miles: Cell[float] = Field(default_factory=Cell)
    foundation_type: Cell[str] = Field(default_factory=Cell)
    public_remarks: Cell[str] = Field(default_factory=Cell)
    extras: dict[str, Any] = Field(default_factory=dict)

    # Computed from the values above.
    distance_miles: Cell[float] = Field(default_factory=Cell)
    gla_diff_pct: Cell[float] = Field(default_factory=Cell)
    age_diff_years: Cell[int] = Field(default_factory=Cell)
    lot_diff_pct: Cell[float] = Field(default_factory=Cell)
    subdivision_score: Cell[float] = Field(default_factory=Cell)
    subdivision_tier: Cell[int] = Field(default_factory=Cell)
    rank: int | None = None  # rank within its pool
    sort_key: list[Any] | None = None  # stored for audit

    def lot_acres(self) -> Fraction | None:
        return lot_acres(self.lot_size_sqft.value, self.lot_size_acres.value)

    def total_baths(self) -> Fraction | None:
        return total_baths(self.baths_full.value, self.baths_half.value)
