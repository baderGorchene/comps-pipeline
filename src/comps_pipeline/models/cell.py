from typing import Generic, TypeVar

from pydantic import BaseModel

from comps_pipeline.models.flag import FlagReason, Source

T = TypeVar("T")


class Cell(BaseModel, Generic[T]):
    """One value plus where it came from. A null value always carries a flag or note."""

    value: T | None = None
    source: Source = Source.NONE
    flag: FlagReason | None = None
    note: str | None = None
