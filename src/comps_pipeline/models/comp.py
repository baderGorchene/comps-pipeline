import datetime as dt
from typing import Any

from pydantic import BaseModel, Field

from comps_pipeline.models.cell import Cell

# Standard comp fields a CSV column can be mapped to (see config/column_mapping.yaml).
STANDARD_FIELDS = (
    "mls_number",
    "close_price",
    "close_date",
    "living_area",
    "year_built",
    "lot_size_sqft",
    "subdivision_raw",
    "latitude",
    "longitude",
    "foundation_type",
    "public_remarks",
)


class Comp(BaseModel):
    mls_number: str
    source_row: int  # 1-based data row in the input CSV, for traceability
    close_price: Cell[int] = Field(default_factory=Cell)
    close_date: Cell[dt.date] = Field(default_factory=Cell)
    living_area: Cell[int] = Field(default_factory=Cell)
    year_built: Cell[int] = Field(default_factory=Cell)
    lot_size_sqft: Cell[int] = Field(default_factory=Cell)
    subdivision_raw: Cell[str] = Field(default_factory=Cell)
    subdivision_normalized: Cell[str] = Field(default_factory=Cell)
    latitude: Cell[float] = Field(default_factory=Cell)
    longitude: Cell[float] = Field(default_factory=Cell)
    foundation_type: Cell[str] = Field(default_factory=Cell)
    public_remarks: Cell[str] = Field(default_factory=Cell)
    extras: dict[str, Any] = Field(default_factory=dict)

    # Computed by Python, never by the LLM.
    distance_miles: Cell[float] = Field(default_factory=Cell)
    gla_diff_pct: Cell[float] = Field(default_factory=Cell)
    age_diff_years: Cell[int] = Field(default_factory=Cell)
    lot_diff_pct: Cell[float] = Field(default_factory=Cell)
    subdivision_score: Cell[float] = Field(default_factory=Cell)
    subdivision_tier: Cell[int] = Field(default_factory=Cell)
    rank: int | None = None
    sort_key: list[Any] | None = None  # stored for audit
