import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Subject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    living_area: int = Field(gt=0)
    subdivision: str
    # Appraisal effective date: reference for "future" and "too old" sale dates.
    effective_date: dt.date
    year_built: int | None = None
    lot_size_sqft: int | None = Field(default=None, gt=0)
    foundation_type: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)
