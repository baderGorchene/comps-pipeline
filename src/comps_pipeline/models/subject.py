import datetime as dt
from fractions import Fraction
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from comps_pipeline.models.comp import lot_acres, total_baths


class Subject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str
    living_area: int = Field(gt=0)
    subdivision: str
    # Appraisal effective date: reference for "future" and "too old" sale dates.
    effective_date: dt.date
    # Optional when the MLS export already reports each comp's distance to the subject.
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    year_built: int | None = None
    lot_size_sqft: int | None = Field(default=None, gt=0)
    lot_size_acres: float | None = Field(default=None, gt=0)
    bedrooms: int | None = Field(default=None, ge=0)
    baths_full: int | None = Field(default=None, ge=0)
    baths_half: int | None = Field(default=None, ge=0)
    foundation_type: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)

    def lot_acres(self) -> Fraction | None:
        return lot_acres(self.lot_size_sqft, self.lot_size_acres)

    def total_baths(self) -> Fraction | None:
        return total_baths(self.baths_full, self.baths_half)
