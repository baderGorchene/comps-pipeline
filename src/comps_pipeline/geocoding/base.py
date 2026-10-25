"""Geocoding interface only. No implementation until the data source is decided (see README)."""

from typing import Protocol

from pydantic import BaseModel


class GeoResult(BaseModel):
    lat: float
    lon: float
    confidence: float


class Geocoder(Protocol):
    def geocode(self, address: str) -> GeoResult | None: ...
